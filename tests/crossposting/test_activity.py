"""GetActivity: the index page's total post count and recent posted_at stamps."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.application.activity import GetActivity
from diffus.crossposting.domain.entities import Post
from tests.crossposting.fakes import FakeUnitOfWork


def make_post(post_id: str, posted_at: datetime) -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=posted_at,
    )


async def test_activity_reports_the_total_and_posted_at_since_the_cutoff():
    uow = FakeUnitOfWork()
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    await uow.posts.upsert(make_post("old", datetime(2026, 1, 1, tzinfo=UTC)))
    await uow.posts.upsert(make_post("new", datetime(2026, 1, 3, tzinfo=UTC)))
    await uow.commit()

    activity = await GetActivity(uow=uow).run(cutoff)

    assert activity.total == 2  # every post, regardless of the cutoff
    assert activity.posted_at == (datetime(2026, 1, 3, tzinfo=UTC),)


async def test_activity_is_empty_with_no_posts():
    activity = await GetActivity(uow=FakeUnitOfWork()).run(datetime(2026, 1, 1, tzinfo=UTC))

    assert activity.total == 0
    assert activity.posted_at == ()
