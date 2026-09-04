"""MediaPublisher: single-image and carousel publishing, readiness polling, error mapping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from diffus.crossposting.domain.entities import AccessToken, MediaType, Token
from diffus.crossposting.domain.errors import PublishError
from diffus.crossposting.infrastructure.instagram.client import MEDIA_FIELDS, InstagramClient


def make_token(external_user_id: str | None = "17841400000000000") -> Token:
    now = datetime.now(UTC)
    return Token(
        source="instagram",
        access_token=AccessToken("super-secret-token"),
        external_user_id=external_user_id,
        expires_at=now + timedelta(days=60),
        refreshed_at=now,
        scopes=InstagramClient.SCOPES,
    )


def make_client(handler, sleep=None) -> InstagramClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    if sleep is None:
        return InstagramClient(
            http, app_id="app-id", app_secret="app-secret", redirect_uri="https://example.com/cb"
        )
    return InstagramClient(
        http,
        app_id="app-id",
        app_secret="app-secret",
        redirect_uri="https://example.com/cb",
        sleep=sleep,
    )


async def noop_sleep(seconds: float) -> None:
    return None


def form(request: httpx.Request) -> httpx.QueryParams:
    return httpx.QueryParams(request.content.decode())


# -- publish_images: single image ----------------------------------------------


async def test_single_image_creates_one_container_waits_then_publishes():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/17841400000000000/media":
            data = form(request)
            assert data["image_url"] == "https://example.com/1.jpg"
            assert data["caption"] == "hello"
            assert "is_carousel_item" not in data
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path == "/container-1":
            assert request.url.params["fields"] == "status_code"
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path == "/17841400000000000/media_publish":
            assert form(request)["creation_id"] == "container-1"
            return httpx.Response(200, json={"id": "ig-media-1"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = make_client(handler)
    token = make_token()

    media_id = await client.publish_images(token, ["https://example.com/1.jpg"], "hello")

    assert media_id == "ig-media-1"
    assert calls == [
        "/17841400000000000/media",
        "/container-1",
        "/17841400000000000/media_publish",
    ]


# -- publish_images: carousel ---------------------------------------------------


async def test_carousel_creates_children_in_order_then_one_album_container():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/17841400000000000/media":
            data = form(request)
            if "is_carousel_item" in data:
                assert data["is_carousel_item"] == "true"
                child_id = "child-1" if data["image_url"].endswith("1.jpg") else "child-2"
                return httpx.Response(200, json={"id": child_id})
            assert data["media_type"] == "CAROUSEL"
            assert data["children"] == "child-1,child-2"
            assert data["caption"] == "hello"
            return httpx.Response(200, json={"id": "album-container"})
        if request.url.path == "/album-container":
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path == "/17841400000000000/media_publish":
            assert form(request)["creation_id"] == "album-container"
            return httpx.Response(200, json={"id": "ig-media-1"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = make_client(handler)
    token = make_token()

    media_id = await client.publish_images(
        token, ["https://example.com/1.jpg", "https://example.com/2.jpg"], "hello"
    )

    assert media_id == "ig-media-1"


# -- readiness polling -----------------------------------------------------------


async def test_readiness_is_polled_until_finished_and_a_missing_user_id_falls_back_to_me():
    statuses = iter(["IN_PROGRESS", "FINISHED"])
    sleep_calls: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/me/media":
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path == "/container-1":
            return httpx.Response(200, json={"status_code": next(statuses)})
        if request.url.path == "/me/media_publish":
            return httpx.Response(200, json={"id": "ig-media-1"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = make_client(handler, sleep=recording_sleep)
    token = make_token(external_user_id=None)

    media_id = await client.publish_images(token, ["https://example.com/1.jpg"], "hello")

    assert media_id == "ig-media-1"
    assert sleep_calls == [2.0]


async def test_readiness_error_status_raises_publish_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/17841400000000000/media":
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path == "/container-1":
            return httpx.Response(200, json={"status_code": "ERROR"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = make_client(handler, sleep=noop_sleep)
    token = make_token()

    with pytest.raises(PublishError):
        await client.publish_images(token, ["https://example.com/1.jpg"], "hello")


async def test_readiness_gives_up_after_ten_attempts():
    sleep_calls: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/17841400000000000/media":
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path == "/container-1":
            return httpx.Response(200, json={"status_code": "IN_PROGRESS"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = make_client(handler, sleep=recording_sleep)
    token = make_token()

    with pytest.raises(PublishError):
        await client.publish_images(token, ["https://example.com/1.jpg"], "hello")

    assert len(sleep_calls) == 10


# -- fetch_post -------------------------------------------------------------------


async def test_fetch_post_requests_media_fields_and_parses_the_single_item():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ig-media-1"
        assert request.url.params["fields"] == MEDIA_FIELDS
        return httpx.Response(
            200,
            json={
                "id": "ig-media-1",
                "caption": "hello",
                "media_type": "IMAGE",
                "media_url": "https://cdn.example.com/1.jpg",
                "permalink": "https://instagram.com/p/ig-media-1/",
                "timestamp": "2024-01-01T12:00:00+00:00",
            },
        )

    client = make_client(handler)
    token = make_token()

    post = await client.fetch_post(token, "ig-media-1")

    assert post.id == "ig-media-1"
    assert post.caption == "hello"
    assert post.permalink == "https://instagram.com/p/ig-media-1/"
    assert post.media[0].type == MediaType.IMAGE
    assert post.media[0].url == "https://cdn.example.com/1.jpg"


async def test_fetch_post_raises_when_the_item_has_no_usable_media():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "ig-media-1",
                "media_type": "IMAGE",
                "permalink": "https://instagram.com/p/ig-media-1/",
                "timestamp": "2024-01-01T12:00:00+00:00",
            },
        )

    client = make_client(handler)
    token = make_token()

    with pytest.raises(PublishError):
        await client.fetch_post(token, "ig-media-1")


# -- error mapping ------------------------------------------------------------------


async def test_a_non_2xx_response_maps_to_a_publish_error_with_the_meta_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid parameter"}})

    client = make_client(handler)
    token = make_token()

    with pytest.raises(PublishError, match="Instagram: Invalid parameter"):
        await client.publish_images(token, ["https://example.com/1.jpg"], "hello")


async def test_a_non_2xx_response_without_a_parseable_body_falls_back_to_the_status_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = make_client(handler)
    token = make_token()

    with pytest.raises(PublishError, match="Instagram: 500"):
        await client.publish_images(token, ["https://example.com/1.jpg"], "hello")


async def test_error_messages_never_contain_the_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "boom"}})

    client = make_client(handler)
    token = make_token()

    with pytest.raises(PublishError) as exc_info:
        await client.publish_images(token, ["https://example.com/1.jpg"], "hello")

    assert token.access_token.value not in str(exc_info.value)
