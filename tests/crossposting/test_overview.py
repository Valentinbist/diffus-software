"""The read-side use cases behind the two pages, against the in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.application.overview import GetOverview, NoEvents
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.domain.entities import (
    Delivery,
    DeliveryStatus,
    Destination,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
    Preview,
)
from tests.crossposting.fakes import FakeEventDirectory, FakeUnitOfWork


def make_post(post_id: str, minute: int = 0) -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, minute, tzinfo=UTC),
    )


async def make_uow() -> FakeUnitOfWork:
    uow = FakeUnitOfWork()
    await uow.posts.upsert(make_post("old"))
    await uow.posts.upsert(make_post("new", minute=5))
    d = Delivery(post_id="new", destination=Destination("telegram", "chat1"))
    d.record_sent(datetime.now(UTC))
    await uow.deliveries.save(d)
    await uow.previews.save(Preview(post_id="new", index=0, content_type="image/jpeg", data=b"x"))
    await uow.commit()
    return uow


async def test_overview_lists_newest_first_with_deliveries_and_stored_previews():
    uow = await make_uow()
    overview = GetOverview(uow=uow, source="instagram")

    result = await overview.run()

    assert result.token is None
    assert [v.post.id for v in result.posts] == ["new", "old"]
    new, old = result.posts
    assert new.deliveries[0].status == DeliveryStatus.SENT
    assert new.stored_previews == frozenset({0})
    assert old.deliveries == []
    assert old.stored_previews == frozenset()


async def test_detail_returns_one_post_or_nothing():
    uow = await make_uow()
    detail = GetPostDetail(uow=uow)

    view = await detail.run("new")
    missing = await detail.run("nope")

    assert view is not None
    assert view.post.id == "new"
    assert view.deliveries[0].destination == Destination("telegram", "chat1")
    assert view.stored_previews == frozenset({0})
    assert missing is None


# -- linked events --------------------------------------------------------------


async def test_overview_attaches_linked_events_from_the_event_directory():
    uow = await make_uow()
    event = LinkedEvent(
        id="e1",
        title="Plenum",
        starts_at=datetime.now(UTC),
        detail_url="/calendar/events/e1",
    )
    overview = GetOverview(uow=uow, source="instagram", events=FakeEventDirectory({"new": [event]}))

    result = await overview.run()

    new, old = result.posts
    assert new.events == [event]
    assert old.events == []


async def test_overview_defaults_to_no_events_when_the_calendar_is_disabled():
    uow = await make_uow()
    overview = GetOverview(uow=uow, source="instagram", events=NoEvents())

    result = await overview.run()

    assert all(view.events == [] for view in result.posts)


async def test_detail_attaches_linked_events_from_the_event_directory():
    uow = await make_uow()
    event = LinkedEvent(
        id="e1",
        title="Plenum",
        starts_at=datetime.now(UTC),
        detail_url="/calendar/events/e1",
    )
    detail = GetPostDetail(uow=uow, events=FakeEventDirectory({"new": [event]}))

    view = await detail.run("new")

    assert view is not None
    assert view.events == [event]
