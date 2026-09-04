"""The pure Post <-> PostRow mapping in the SQL repository, exercised without a DB."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.domain.entities import (
    Destination,
    MediaItem,
    MediaType,
    Post,
    PublishTargets,
)
from diffus.crossposting.infrastructure.db.models import PostRow
from diffus.crossposting.infrastructure.db.repositories import (
    _json_to_targets,
    _post_to_row,
    _row_to_post,
    _targets_to_json,
)

POSTED_AT = datetime(2024, 1, 1, 12, tzinfo=UTC)


def test_media_thumbnail_survives_row_round_trip():
    post = Post(
        id="1",
        source="instagram",
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
        source="instagram",
        caption=None,
        permalink="https://instagram.com/p/legacy/",
        media=[{"url": "https://cdn.example.com/legacy.mp4", "type": "video"}],
        posted_at=POSTED_AT,
    )

    post = _row_to_post(row)

    assert post.media[0].thumbnail_url is None
    assert post.cover_url is None  # a video with no still frame has nothing to show


# -- PublishTargets <-> JSONB (post_drafts.targets) ---------------------------


def test_publish_targets_round_trip_through_json():
    targets = PublishTargets(
        instagram=True,
        destinations=(Destination("telegram", "c1"), Destination("signal", "c2")),
    )

    data = _targets_to_json(targets)

    assert data == {"instagram": True, "destinations": ["telegram:c1", "signal:c2"]}
    assert _json_to_targets(data) == targets


def test_no_targets_round_trips_through_none():
    assert _targets_to_json(None) is None
    assert _json_to_targets(None) is None
