"""SyncCalendar: fetch outside any unit of work, then upsert + mark_removed inside one."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.domain.entities import CalendarEvent, CalendarSnapshot, SubCalendar
from diffus.calendar.domain.ports import EventRepository
from tests.calendar.fakes import FailingCalendar, FakeCalendar, FakeCalendarUnitOfWork, FakeEvents

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


async def get_event(events: EventRepository, event_id: str) -> CalendarEvent:
    stored = await events.get(event_id)
    assert stored is not None
    return stored


def make_sub_calendar(sub_calendar_id: int = 1) -> SubCalendar:
    return SubCalendar(id=sub_calendar_id, name="Haupt-Raum", color="#31859B", position=0)


def make_event(
    event_id: str, starts_at: datetime = NOW, removed_at: datetime | None = None
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title="Test",
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
        removed_at=removed_at,
    )


async def test_first_run_stores_sub_calendars_and_events_and_commits_once():
    sub_calendar = make_sub_calendar()
    event = make_event("e1")
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(sub_calendar,), events=(event,)))
    uow = FakeCalendarUnitOfWork()
    sync = SyncCalendar(calendar=calendar, uow=uow)

    report = await sync.run(now=NOW)

    assert report.sub_calendars == 1
    assert report.fetched == 1
    assert report.removed == 0
    assert uow.commits == 1
    stored = await get_event(uow.events, "e1")
    assert stored.removed_at is None
    assert await uow.sub_calendars.list_all() == [sub_calendar]


async def test_second_run_marks_only_the_vanished_event_removed():
    e1, e2 = make_event("e1"), make_event("e2")
    uow = FakeCalendarUnitOfWork(events=FakeEvents([e1, e2]))
    # e2 no longer comes back from the source.
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(), events=(e1,)))
    sync = SyncCalendar(calendar=calendar, uow=uow)

    report = await sync.run(now=NOW)

    assert report.removed == 1
    assert (await get_event(uow.events, "e1")).removed_at is None
    assert (await get_event(uow.events, "e2")).removed_at == NOW


async def test_an_event_outside_the_window_is_untouched_even_when_missing():
    outside = make_event("old", starts_at=datetime(2020, 1, 1, tzinfo=UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([outside]))
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(), events=(make_event("e1"),)))
    sync = SyncCalendar(calendar=calendar, uow=uow)

    report = await sync.run(now=NOW)

    assert report.removed == 0
    assert (await get_event(uow.events, "old")).removed_at is None


async def test_a_removed_event_that_comes_back_is_un_removed():
    e1 = make_event("e1", removed_at=NOW - timedelta(days=1))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([e1]))
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(), events=(make_event("e1"),)))
    sync = SyncCalendar(calendar=calendar, uow=uow)

    await sync.run(now=NOW)

    assert (await get_event(uow.events, "e1")).removed_at is None


async def test_an_empty_snapshot_marks_nothing_removed():
    e1 = make_event("e1")
    uow = FakeCalendarUnitOfWork(events=FakeEvents([e1]))
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(), events=()))
    sync = SyncCalendar(calendar=calendar, uow=uow)

    report = await sync.run(now=NOW)

    assert report.removed == 0
    assert report.fetched == 0
    assert (await get_event(uow.events, "e1")).removed_at is None
    assert uow.commits == 1


async def test_the_fetch_window_is_month_aligned():
    calendar = FakeCalendar(CalendarSnapshot(sub_calendars=(), events=()))
    uow = FakeCalendarUnitOfWork()
    sync = SyncCalendar(calendar=calendar, uow=uow, past_months=3, future_months=6)

    await sync.run(now=NOW)

    assert calendar.calls == [(date(2026, 6, 1), date(2027, 3, 31))]


async def test_a_failing_gateway_raises_and_leaves_stored_events_untouched():
    e1 = make_event("e1")
    uow = FakeCalendarUnitOfWork(events=FakeEvents([e1]))
    calendar = FailingCalendar(RuntimeError("kalender.digital is down"))
    sync = SyncCalendar(calendar=calendar, uow=uow)

    with pytest.raises(RuntimeError):
        await sync.run(now=NOW)

    assert uow.commits == 0
    assert await get_event(uow.events, "e1") == e1
