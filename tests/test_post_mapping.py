"""The pure Post <-> PostRow mapping in the SQL repository, exercised without a DB."""

from __future__ import annotations

from datetime import UTC, datetime

from connector.domain.entities import MediaItem, MediaType, Post
from connector.infrastructure.db.models import PostRow
from connector.infrastructure.db.repositories import _post_to_row, _row_to_post

POSTED_AT = datetime(2024, 1, 1, 12, tzinfo=UTC)


def test_media_thumbnail_survives_row_round_trip():
    post = Post(
        id="1",
        caption="c",
        permalink="https://instagram.com/p/1/",
        media=(
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
            MediaItem(
                url="https://cdn.example.com/2.mp4",
                type=MediaType.VIDEO,
                thumbnail_url="https://cdn.example.com/2-thumb.jpg",
            ),
        ),
        posted_at=POSTED_AT,
    )

    row = PostRow(**_post_to_row(post))

    assert _row_to_post(row) == post


def test_rows_written_before_thumbnails_were_stored_still_load():
    row = PostRow(
        id="legacy",
        caption=None,
        permalink="https://instagram.com/p/legacy/",
        media=[{"url": "https://cdn.example.com/legacy.mp4", "type": "video"}],
        posted_at=POSTED_AT,
    )

    post = _row_to_post(row)

    assert post.media[0].thumbnail_url is None
    assert post.cover_url is None  # a video with no still frame has nothing to show
