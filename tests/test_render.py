from __future__ import annotations

from datetime import UTC, datetime

from connector.domain.entities import MediaItem, MediaType, Post
from connector.infrastructure.telegram.render import MAX_CAPTION_LENGTH, render_caption


def make_post(caption: str | None) -> Post:
    return Post(
        id="1",
        source="instagram",
        caption=caption,
        permalink="https://instagram.com/p/ABC123/",
        media=(MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_render_caption_truncates_long_caption_and_contains_permalink():
    post = make_post("x" * 2000)

    rendered = render_caption(post)

    assert len(rendered) <= MAX_CAPTION_LENGTH
    assert post.permalink in rendered
    assert "…" in rendered


def test_render_caption_keeps_short_caption_untouched_and_contains_permalink():
    post = make_post("short caption")

    rendered = render_caption(post)

    assert "short caption" in rendered
    assert post.permalink in rendered
    assert len(rendered) <= MAX_CAPTION_LENGTH


def test_render_caption_handles_missing_caption():
    post = make_post(None)

    rendered = render_caption(post)

    assert post.permalink in rendered
