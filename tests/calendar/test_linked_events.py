"""GetLinkedEvents: which calendar events are linked to a given set of posts."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent
from tests.calendar.fakes import FakeCalendarUnitOfWork, FakeEventLinks, FakeEvents


def make_event(event_id: str, starts_at: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=f"Event {event_id}",
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=starts_at,
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
    )


async def test_for_posts_returns_a_posts_linked_events_sorted_by_start():
    early = make_event("e-early", datetime(2026, 9, 1, tzinfo=UTC))
    late = make_event("e-late", datetime(2026, 9, 10, tzinfo=UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([early, late]), event_links=FakeEventLinks())
    await uow.event_links.add(late.id, "p1")
    await uow.event_links.add(early.id, "p1")
    await uow.commit()
    linked_events = GetLinkedEvents(uow=uow)

    found = await linked_events.for_posts(["p1", "p2"])

    assert set(found) == {"p1"}
    assert [e.id for e in found["p1"]] == ["e-early", "e-late"]


async def test_for_posts_with_no_ids_returns_nothing():
    uow = FakeCalendarUnitOfWork()
    linked_events = GetLinkedEvents(uow=uow)

    assert await linked_events.for_posts([]) == {}
