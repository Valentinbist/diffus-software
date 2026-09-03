"""The pure CalendarEvent <-> EventRow mapping in the SQL repository, exercised without a DB."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.calendar.domain.entities import CalendarEvent, EventLink, SubCalendar
from diffus.calendar.infrastructure.db.models import EventPostRow, EventRow, SubCalendarRow
from diffus.calendar.infrastructure.db.repositories import (
    _event_to_row,
    _row_to_event,
    _row_to_link,
    _row_to_sub_calendar,
    _sub_calendar_to_row,
)

STARTS_AT = datetime(2026, 8, 3, 16, 0, tzinfo=UTC)
ENDS_AT = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)


def test_event_round_trips_through_its_row():
    event = CalendarEvent(
        id="3571355485",
        title="Widersetzen Plenum",
        description="Text",
        who="Jona",
        location="Hof",
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        whole_day=False,
        sub_calendar_ids=frozenset({472104, 5298948}),
        series_id=1756742227,
        removed_at=None,
    )

    row = EventRow(**_event_to_row(event))

    assert _row_to_event(row, event.sub_calendar_ids) == event


def test_removed_at_survives_the_round_trip():
    removed_at = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    event = CalendarEvent(
        id="gone",
        title="",
        description=None,
        who=None,
        location=None,
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        whole_day=True,
        sub_calendar_ids=frozenset(),
        series_id=None,
        removed_at=removed_at,
    )

    row = EventRow(**_event_to_row(event))
    rebuilt = _row_to_event(row, frozenset())

    assert rebuilt == event
    assert rebuilt.removed_at == removed_at
    assert rebuilt.removed


def test_sub_calendar_round_trips_through_its_row():
    sub_calendar = SubCalendar(id=472104, name="Haupt-Raum", color="#31859B", position=0)

    row = SubCalendarRow(**_sub_calendar_to_row(sub_calendar))

    assert _row_to_sub_calendar(row) == sub_calendar


def test_row_to_link_maps_every_field():
    linked_at = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    row = EventPostRow(event_id="3571355485", post_id="p1", linked_at=linked_at)

    assert _row_to_link(row) == EventLink(
        event_id="3571355485", post_id="p1", linked_at=linked_at
    )
