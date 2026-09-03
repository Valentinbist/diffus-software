from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from connector.domain.entities import AccessToken, MediaType, Token
from connector.infrastructure.instagram.client import InstagramClient

CAROUSEL_PAYLOAD = {
    "data": [
        {
            "id": "123",
            "caption": "hello world",
            "media_type": "CAROUSEL_ALBUM",
            "permalink": "https://instagram.com/p/123/",
            "timestamp": "2024-01-01T12:00:00+00:00",
            "children": {
                "data": [
                    {"media_type": "IMAGE", "media_url": "https://cdn.example.com/1.jpg"},
                    {
                        "media_type": "VIDEO",
                        "media_url": "https://cdn.example.com/2.mp4",
                        "thumbnail_url": "https://cdn.example.com/2-thumb.jpg",
                    },
                    # No usable URL at all: must be skipped, not crash the parse.
                    {"media_type": "IMAGE"},
                ]
            },
        },
        {
            # Single-media post (not a carousel).
            "id": "456",
            "caption": None,
            "media_type": "IMAGE",
            "media_url": "https://cdn.example.com/single.jpg",
            "permalink": "https://instagram.com/p/456/",
            "timestamp": "2024-01-02T08:30:00+00:00",
        },
        {
            # Video whose media_url is missing: falls back to thumbnail as an IMAGE.
            "id": "789",
            "caption": "video without media_url",
            "media_type": "VIDEO",
            "thumbnail_url": "https://cdn.example.com/789-thumb.jpg",
            "permalink": "https://instagram.com/p/789/",
            "timestamp": "2024-01-03T08:30:00+00:00",
        },
    ]
}


def test_parse_carousel_album_expands_children_and_skips_unusable_media():
    posts = InstagramClient._parse(CAROUSEL_PAYLOAD)

    carousel = next(p for p in posts if p.id == "123")
    assert carousel.caption == "hello world"
    assert carousel.permalink == "https://instagram.com/p/123/"
    assert len(carousel.media) == 2  # third child had no usable URL, must be dropped
    assert carousel.media[0].type == MediaType.IMAGE
    assert carousel.media[0].url == "https://cdn.example.com/1.jpg"
    assert carousel.media[1].type == MediaType.VIDEO
    assert carousel.media[1].url == "https://cdn.example.com/2.mp4"


def test_parse_keeps_video_thumbnail_and_exposes_previews():
    posts = InstagramClient._parse(CAROUSEL_PAYLOAD)

    carousel = next(p for p in posts if p.id == "123")
    image, video = carousel.media
    assert image.thumbnail_url is None
    assert image.preview_url == "https://cdn.example.com/1.jpg"
    assert video.thumbnail_url == "https://cdn.example.com/2-thumb.jpg"
    assert video.preview_url == "https://cdn.example.com/2-thumb.jpg"
    assert carousel.cover_url == "https://cdn.example.com/1.jpg"


def test_parse_single_media_post():
    posts = InstagramClient._parse(CAROUSEL_PAYLOAD)

    single = next(p for p in posts if p.id == "456")
    assert single.source == "instagram"
    assert len(single.media) == 1
    assert single.media[0].type == MediaType.IMAGE
    assert single.media[0].url == "https://cdn.example.com/single.jpg"


def test_parse_video_without_media_url_falls_back_to_thumbnail_as_image():
    posts = InstagramClient._parse(CAROUSEL_PAYLOAD)

    video_fallback = next(p for p in posts if p.id == "789")
    assert len(video_fallback.media) == 1
    assert video_fallback.media[0].type == MediaType.IMAGE
    assert video_fallback.media[0].url == "https://cdn.example.com/789-thumb.jpg"


def test_parse_skips_posts_with_zero_usable_media():
    payload = {
        "data": [
            {
                "id": "empty",
                "caption": "no media",
                "media_type": "IMAGE",
                "permalink": "https://instagram.com/p/empty/",
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        ]
    }

    posts = InstagramClient._parse(payload)

    assert posts == []


# -- AuthGateway: exchange_code / refresh, against a mocked transport ---------


def make_client(handler) -> InstagramClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return InstagramClient(
        http, app_id="app-id", app_secret="app-secret", redirect_uri="https://example.com/cb"
    )


async def test_exchange_code_does_the_short_to_long_lived_two_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.instagram.com":
            assert request.url.path == "/oauth/access_token"
            return httpx.Response(
                200, json={"access_token": "short-lived-xyz", "user_id": 17841400000000000}
            )
        assert request.url.host == "graph.instagram.com"
        assert request.url.path == "/access_token"
        assert request.url.params["grant_type"] == "ig_exchange_token"
        assert request.url.params["access_token"] == "short-lived-xyz"
        return httpx.Response(200, json={"access_token": "long-lived-abc", "expires_in": 5_184_000})

    client = make_client(handler)

    token = await client.exchange_code("some-code")

    assert token.source == "instagram"
    assert token.external_user_id == "17841400000000000"
    assert isinstance(token.access_token, AccessToken)
    assert token.access_token.value == "long-lived-abc"


async def test_refresh_keeps_source_and_user_id_and_sends_the_old_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.instagram.com"
        assert request.url.path == "/refresh_access_token"
        assert request.url.params["grant_type"] == "ig_refresh_token"
        assert request.url.params["access_token"] == "old-token"
        return httpx.Response(200, json={"access_token": "new-token", "expires_in": 5_184_000})

    client = make_client(handler)
    now = datetime.now(UTC)
    old_token = Token(
        source="instagram",
        access_token=AccessToken("old-token"),
        external_user_id="17841400000000000",
        expires_at=now + timedelta(days=10),
        refreshed_at=now - timedelta(days=50),
    )

    refreshed = await client.refresh(old_token)

    assert refreshed.source == "instagram"
    assert refreshed.external_user_id == "17841400000000000"
    assert refreshed.access_token.value == "new-token"
