from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.domain.entities import MediaItem, MediaType, Post
from diffus.crossposting.infrastructure.telegram.render import MAX_CAPTION_LENGTH, render_caption


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


def test_render_caption_omits_the_instagram_link_when_there_is_no_permalink():
    # App-originated ("diffus:...") posts have no Instagram permalink at all.
    post = Post(
        id="diffus:abc",
        source="diffus",
        caption="Siebdruck-Nachmittag",
        permalink="",
        media=(MediaItem(url="https://example.com/1.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    rendered = render_caption(post)

    assert rendered == "Siebdruck-Nachmittag"
    assert "Instagram" not in rendered
    assert "<a href" not in rendered
