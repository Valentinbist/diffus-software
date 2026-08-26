from __future__ import annotations

from connector.domain.entities import MediaType
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


def test_parse_single_media_post():
    posts = InstagramClient._parse(CAROUSEL_PAYLOAD)

    single = next(p for p in posts if p.id == "456")
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
