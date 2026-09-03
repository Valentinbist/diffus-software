"""Behaviour that lives on the domain objects themselves: no ports, no fakes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from diffus.calendar.domain.entities import CalendarEvent

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def make_event(
    starts_at: datetime,
    ends_at: datetime,
    whole_day: bool = False,
    removed_at: datetime | None = None,
) -> CalendarEvent:
    return CalendarEvent(
        id="e1",
        title="Test",
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=ends_at,
        whole_day=whole_day,
        sub_calendar_ids=frozenset(),
        series_id=None,
        removed_at=removed_at,
    )


# -- local_days / is_on --------------------------------------------------


def test_a_timed_event_within_one_day_lands_on_a_single_local_day():
    event = make_event(
        starts_at=datetime(2026, 8, 3, 16, 0, tzinfo=UTC),  # 18:00 CEST
        ends_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),  # 20:00 CEST
    )

    assert event.local_days(TZ) == [date(2026, 8, 3)]
    assert event.is_on(date(2026, 8, 3), TZ)
    assert not event.is_on(date(2026, 8, 4), TZ)


def test_a_timed_event_ending_exactly_at_local_midnight_does_not_spill_into_the_next_day():
    event = make_event(
        starts_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),  # 20:00 CEST
        ends_at=datetime(2026, 8, 3, 22, 0, tzinfo=UTC),  # 00:00 CEST on the 4th
    )

    assert event.local_days(TZ) == [date(2026, 8, 3)]


def test_a_timed_event_crossing_midnight_lands_on_two_local_days():
    event = make_event(
        starts_at=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),  # 22:00 CEST
        ends_at=datetime(2026, 8, 4, 0, 0, tzinfo=UTC),  # 02:00 CEST on the 4th
    )

    assert event.local_days(TZ) == [date(2026, 8, 3), date(2026, 8, 4)]
    assert event.is_on(date(2026, 8, 3), TZ)
    assert event.is_on(date(2026, 8, 4), TZ)


def test_a_one_day_whole_day_event_lands_on_a_single_local_day():
    event = make_event(
        starts_at=datetime(2026, 8, 7, 22, 0, tzinfo=UTC),  # 2026-08-08 00:00 CEST
        ends_at=datetime(2026, 8, 8, 22, 0, tzinfo=UTC),  # 2026-08-09 00:00 CEST, exclusive
        whole_day=True,
    )

    assert event.local_days(TZ) == [date(2026, 8, 8)]


def test_a_two_day_whole_day_event_lands_on_both_local_days():
    event = make_event(
        starts_at=datetime(2026, 8, 27, 22, 0, tzinfo=UTC),  # 2026-08-28 00:00 CEST
        ends_at=datetime(2026, 8, 29, 22, 0, tzinfo=UTC),  # 2026-08-30 00:00 CEST, exclusive
        whole_day=True,
    )

    assert event.local_days(TZ) == [date(2026, 8, 28), date(2026, 8, 29)]


def test_a_zero_length_event_yields_only_its_start_day():
    moment = datetime(2026, 8, 3, 16, 0, tzinfo=UTC)
    event = make_event(starts_at=moment, ends_at=moment)

    assert event.local_days(TZ) == [date(2026, 8, 3)]


# -- removed ---------------------------------------------------------------


def test_an_event_is_not_removed_until_removed_at_is_set():
    event = make_event(starts_at=NOW, ends_at=NOW)
    assert not event.removed

    removed_event = dataclasses.replace(event, removed_at=NOW)
    assert removed_event.removed
