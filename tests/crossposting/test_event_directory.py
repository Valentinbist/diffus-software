"""CalendarEventDirectory: EventDirectory over the calendar context's own read use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent, EventLink
from diffus.crossposting.infrastructure.calendar import CalendarEventDirectory
from tests.calendar.fakes import FakeCalendarUnitOfWork, FakeEventLinks, FakeEvents


def make_event(
    event_id: str, title: str = "Plenum", removed_at: datetime | None = None
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
        removed_at=removed_at,
    )


async def make_directory(
    events: list[CalendarEvent], links: list[EventLink]
) -> CalendarEventDirectory:
    uow = FakeCalendarUnitOfWork(events=FakeEvents(events), event_links=FakeEventLinks())
    for link in links:
        await uow.event_links.add(link.event_id, link.post_id)
    await uow.commit()
    return CalendarEventDirectory(linked=GetLinkedEvents(uow=uow))


async def test_for_posts_maps_calendar_events_to_the_connectors_own_linked_event():
    event = make_event("e1", title="Widersetzen Plenum")
    directory = await make_directory([event], [EventLink(event.id, "p1", datetime.now(UTC))])

    found = await directory.for_posts(["p1", "p2"])

    assert set(found) == {"p1"}
    linked = found["p1"][0]
    assert linked.id == "e1"
    assert linked.title == "Widersetzen Plenum"
    assert linked.detail_url == "/calendar/events/e1"
    assert linked.removed is False


async def test_for_posts_marks_a_removed_event_but_still_returns_it():
    event = make_event("e1", removed_at=datetime.now(UTC))
    directory = await make_directory([event], [EventLink(event.id, "p1", datetime.now(UTC))])

    found = await directory.for_posts(["p1"])

    assert found["p1"][0].removed is True
