"""Runs the real InstagramClient against mocks/instagram.py, over ASGITransport.

The mock's own outbound fetch of `image_url` (what `POST /{user}/media` does,
just like real Instagram) has no real socket to hit here, so `state.fetch`
is swapped for one that goes through the same ASGI app instead of a real
`httpx.AsyncClient` — see mocks/instagram.py's `FetchFn` docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from diffus.crossposting.domain.entities import AccessToken, Token
from diffus.crossposting.domain.errors import PublishError
from diffus.crossposting.infrastructure.instagram.client import InstagramClient
from mocks.instagram import State, create_app

REDIRECT_URI = "http://t/cb"


async def noop_sleep(seconds: float) -> None:
    return None


@pytest.fixture
def state() -> State:
    s = State()
    s.seed()
    return s


@pytest.fixture
async def http(state: State):
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as client:
        # The mock's own "download image_url" step must reach the very same
        # ASGI app, not a real socket — see the module docstring.
        async def asgi_fetch(url: str) -> tuple[str, bytes]:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            return content_type, resp.content

        state.fetch = asgi_fetch
        yield client


def make_client(http: httpx.AsyncClient) -> InstagramClient:
    return InstagramClient(
        http,
        app_id="mock",
        app_secret="mock",
        redirect_uri=REDIRECT_URI,
        graph_base="http://mock/graph",
        api_base="http://mock/api",
        authorize_url="http://mock/www/oauth/authorize",
        sleep=noop_sleep,
    )


async def do_oauth(http: httpx.AsyncClient, client: InstagramClient) -> Token:
    """authorize_url() -> follow the redirect -> exchange the code -> a real Token."""
    path = client.authorize_url().removeprefix("http://mock")
    resp = await http.get(path, follow_redirects=False)
    assert resp.status_code == 302
    code = resp.headers["location"].split("code=")[1]
    return await client.exchange_code(code)


# -- OAuth: authorize -> exchange -> refresh --------------------------------


async def test_authorize_url_redirects_with_a_code(http: httpx.AsyncClient):
    client = make_client(http)

    path = client.authorize_url().removeprefix("http://mock")
    resp = await http.get(path, follow_redirects=False)

    assert resp.status_code == 302
    assert "code=mock-code-" in resp.headers["location"]
    assert resp.headers["location"].startswith(REDIRECT_URI)


async def test_exchange_code_returns_a_token_with_external_user_id_and_publish_scope(
    http: httpx.AsyncClient,
):
    client = make_client(http)

    token = await do_oauth(http, client)

    assert token.source == "instagram"
    assert token.external_user_id == "17841400000000001"
    assert token.can_publish


async def test_refresh_returns_a_new_token(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    refreshed = await client.refresh(token)

    assert refreshed.access_token.value != token.access_token.value
    assert refreshed.external_user_id == token.external_user_id


# -- fetch_recent: the 4 seeded posts ----------------------------------------


async def test_fetch_recent_returns_the_four_seeded_posts(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    posts = await client.fetch_recent(token)

    assert [p.id for p in posts] == ["seed-1", "seed-2", "seed-3", "seed-4"]


async def test_fetch_recent_expands_the_carousel_children(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    posts = await client.fetch_recent(token)

    carousel = next(p for p in posts if p.id == "seed-2")
    assert len(carousel.media) == 3


async def test_fetch_recent_video_has_a_thumbnail_preview(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    posts = await client.fetch_recent(token)

    video_post = next(p for p in posts if p.id == "seed-3")
    assert len(video_post.media) == 1
    assert video_post.media[0].thumbnail_url is not None
    assert video_post.media[0].preview_url == video_post.media[0].thumbnail_url


async def test_fetch_recent_honours_limit(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    posts = await client.fetch_recent(token, limit=2)

    assert len(posts) == 2


# -- publish_images: single and carousel, against the mock's own media ------


async def test_publish_single_image_then_fetch_post_returns_it_at_the_top(
    http: httpx.AsyncClient,
):
    client = make_client(http)
    token = await do_oauth(http, client)

    media_id = await client.publish_images(
        token, ["http://mock/graph/mock-media/seed-1.jpg"], "brand new post"
    )
    post = await client.fetch_post(token, media_id)

    assert post.caption == "brand new post"

    recent = await client.fetch_recent(token)
    assert recent[0].id == media_id


async def test_publish_carousel_of_two_images(http: httpx.AsyncClient):
    client = make_client(http)
    token = await do_oauth(http, client)

    media_id = await client.publish_images(
        token,
        [
            "http://mock/graph/mock-media/seed-2-1.jpg",
            "http://mock/graph/mock-media/seed-2-2.jpg",
        ],
        "a carousel",
    )

    post = await client.fetch_post(token, media_id)
    assert len(post.media) == 2


# -- errors -------------------------------------------------------------------


async def test_a_bad_image_url_fails_the_container_and_raises_publish_error(
    http: httpx.AsyncClient,
):
    client = make_client(http)
    token = await do_oauth(http, client)

    with pytest.raises(PublishError):
        await client.publish_images(
            token, ["http://mock/graph/mock-media/does-not-exist.jpg"], "oops"
        )


async def test_a_wrong_access_token_raises_publish_error(http: httpx.AsyncClient):
    """fetch_post (unlike fetch_recent/exchange_code/refresh) goes through InstagramClient's
    own _request(), which is what maps the mock's 400 error body to a PublishError."""
    client = make_client(http)
    bogus = Token(
        source="instagram",
        access_token=AccessToken("not-a-real-token"),
        external_user_id="1",
        expires_at=datetime.now(UTC) + timedelta(days=60),
        refreshed_at=datetime.now(UTC),
    )

    with pytest.raises(PublishError):
        await client.fetch_post(bogus, "seed-1")


async def test_quota_knob_blocks_publish_once_the_limit_is_reached(
    http: httpx.AsyncClient, state: State
):
    client = make_client(http)
    token = await do_oauth(http, client)
    state.quota_limit = 1

    await client.publish_images(token, ["http://mock/graph/mock-media/seed-1.jpg"], "one")

    with pytest.raises(PublishError, match="Application request limit reached"):
        await client.publish_images(token, ["http://mock/graph/mock-media/seed-1.jpg"], "two")
