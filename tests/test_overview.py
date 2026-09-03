"""The read-side use cases behind the two pages, against the in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime

from connector.application.overview import GetOverview
from connector.application.post_detail import GetPostDetail
from connector.domain.entities import DeliveryStatus, MediaItem, MediaType, Post, Preview
from tests.fakes import FakeDeliveries, FakePosts, FakePreviews, FakeTokens


def make_post(post_id: str, minute: int = 0) -> Post:
    return Post(
        id=post_id,
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, minute, tzinfo=UTC),
    )


async def make_repos():
    posts, deliveries, previews = FakePosts(), FakeDeliveries(), FakePreviews()
    await posts.upsert(make_post("old"))
    await posts.upsert(make_post("new", minute=5))
    await deliveries.mark("new", "chat1", DeliveryStatus.SENT)
    await previews.save(Preview(post_id="new", index=0, content_type="image/jpeg", data=b"x"))
    return posts, deliveries, previews


async def test_overview_lists_newest_first_with_deliveries_and_stored_previews():
    posts, deliveries, previews = await make_repos()
    overview = GetOverview(
        tokens=FakeTokens(), posts=posts, deliveries=deliveries, previews=previews
    )

    result = await overview.run()

    assert result.token is None
    assert [v.post.id for v in result.posts] == ["new", "old"]
    new, old = result.posts
    assert new.deliveries[0].status == DeliveryStatus.SENT
    assert new.stored_previews == frozenset({0})
    assert old.deliveries == []
    assert old.stored_previews == frozenset()


async def test_detail_returns_one_post_or_nothing():
    posts, deliveries, previews = await make_repos()
    detail = GetPostDetail(posts=posts, deliveries=deliveries, previews=previews)

    view = await detail.run("new")
    missing = await detail.run("nope")

    assert view is not None
    assert view.post.id == "new"
    assert view.deliveries[0].chat_id == "chat1"
    assert view.stored_previews == frozenset({0})
    assert missing is None
