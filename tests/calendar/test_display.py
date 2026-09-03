"""Calendar presentation display helpers: pure formatting and date-window math."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import EventPostStatus, EventView
from diffus.calendar.application.suggest_posts import SuggestionReason
from diffus.calendar.domain.entities import CalendarEvent
from diffus.calendar.presentation.display import (
    by_day,
    filter_by_status,
    format_agenda_day,
    format_event_time,
    month_grid,
    month_label,
    month_range,
    parse_day,
    parse_month,
    post_status_label,
    reason_label,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # Donnerstag, 3. September in Berlin


def make_event(
    starts_at: datetime, ends_at: datetime | None = None, whole_day: bool = False
) -> CalendarEvent:
    return CalendarEvent(
        id="e1",
        title="Test",
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=ends_at if ends_at is not None else starts_at + timedelta(hours=1),
        whole_day=whole_day,
        sub_calendar_ids=frozenset(),
        series_id=None,
    )


def make_view(event: CalendarEvent) -> EventView:
    return EventView(event=event, sub_calendars=[], links=[], post_status=EventPostStatus.NONE)


# -- format_event_time --------------------------------------------------------


def test_format_event_time_for_a_single_day_whole_day_event():
    event = make_event(
        starts_at=datetime(2026, 8, 7, 22, 0, tzinfo=UTC),
        ends_at=datetime(2026, 8, 8, 22, 0, tzinfo=UTC),
        whole_day=True,
    )
    assert format_event_time(event, TZ) == "ganztägig"


def test_format_event_time_for_a_two_day_whole_day_event():
    event = make_event(
        starts_at=datetime(2026, 8, 27, 22, 0, tzinfo=UTC),
        ends_at=datetime(2026, 8, 29, 22, 0, tzinfo=UTC),
        whole_day=True,
    )
    assert format_event_time(event, TZ) == "ganztägig bis 29. August"


def test_format_event_time_for_a_timed_event_within_one_day():
    event = make_event(
        starts_at=datetime(2026, 8, 3, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
    )
    assert format_event_time(event, TZ) == "18:00–20:00"


def test_format_event_time_for_a_timed_event_crossing_midnight():
    event = make_event(
        starts_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),  # 16:00 CEST, Oct 10
        ends_at=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),  # 15:00 CEST, Oct 11
    )
    assert format_event_time(event, TZ) == "16:00 – 11. Oktober, 15:00"


# -- format_agenda_day ---------------------------------------------------------


def test_format_agenda_day_today():
    assert format_agenda_day(date(2026, 9, 3), NOW, TZ) == "Heute · Donnerstag, 3. September"


def test_format_agenda_day_tomorrow():
    assert format_agenda_day(date(2026, 9, 4), NOW, TZ) == "Morgen · Freitag, 4. September"


def test_format_agenda_day_other_weekday_this_year():
    assert format_agenda_day(date(2026, 9, 5), NOW, TZ) == "Samstag, 5. September"


def test_format_agenda_day_outside_this_year_includes_the_year():
    assert format_agenda_day(date(2027, 9, 5), NOW, TZ) == "Sonntag, 5. September 2027"


# -- month_grid -----------------------------------------------------------------


def test_month_grid_for_september_2026_has_five_weeks_starting_on_a_monday():
    grid = month_grid([], 2026, 9, NOW, TZ)

    assert len(grid.weeks) == 5
    assert all(len(week) == 7 for week in grid.weeks)
    assert grid.weeks[0][0].day == date(2026, 8, 31)
    assert grid.label == "September 2026"
    assert grid.prev == "2026-08"
    assert grid.next == "2026-10"


def test_month_grid_for_february_2027_has_four_weeks():
    grid = month_grid([], 2027, 2, NOW, TZ)

    assert len(grid.weeks) == 4


def test_month_grid_flags_todays_cell():
    grid = month_grid([], 2026, 9, NOW, TZ)

    todays = [d for week in grid.weeks for d in week if d.is_today]
    assert [c.day for c in todays] == [date(2026, 9, 3)]


def test_month_grid_places_a_two_day_whole_day_event_on_both_its_local_days():
    event = make_event(
        starts_at=datetime(2026, 8, 30, 22, 0, tzinfo=UTC),  # 2026-08-31 00:00 CEST
        ends_at=datetime(2026, 9, 1, 22, 0, tzinfo=UTC),  # 2026-09-02 00:00 CEST, exclusive
        whole_day=True,
    )
    view = make_view(event)

    grid = month_grid([view], 2026, 9, NOW, TZ)

    cells = [d.day for week in grid.weeks for d in week if view in d.events]
    assert cells == [date(2026, 8, 31), date(2026, 9, 1)]


def test_month_grid_does_not_spill_a_timed_event_ending_at_local_midnight():
    event = make_event(
        starts_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),  # 20:00 CEST
        ends_at=datetime(2026, 9, 5, 22, 0, tzinfo=UTC),  # 00:00 CEST the next day
    )
    view = make_view(event)

    grid = month_grid([view], 2026, 9, NOW, TZ)

    cells = [d.day for week in grid.weeks for d in week if view in d.events]
    assert cells == [date(2026, 9, 5)]


def test_month_range_matches_the_grids_first_and_last_visible_days():
    assert month_range(2026, 9) == (date(2026, 8, 31), date(2026, 10, 4))
    assert month_range(2027, 2) == (date(2027, 2, 1), date(2027, 2, 28))


# -- by_day -----------------------------------------------------------------


def test_by_day_floors_an_event_that_started_before_the_visible_window():
    running = make_event(starts_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC))
    view = make_view(running)
    floor = date(2026, 9, 1)

    grouped = by_day([view], floor, TZ)

    assert grouped == [(floor, [view])]


def test_by_day_keeps_an_event_on_its_own_day_when_it_starts_after_the_floor():
    event = make_event(starts_at=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    view = make_view(event)

    grouped = by_day([view], date(2026, 9, 1), TZ)

    assert grouped == [(date(2026, 9, 5), [view])]


# -- parsing and labels -------------------------------------------------------


def test_parse_day_rejects_garbage():
    assert parse_day("nope") is None
    assert parse_day(None) is None
    assert parse_day("2026-09-05") == date(2026, 9, 5)


def test_parse_month_rejects_an_out_of_range_month():
    assert parse_month("2026-13") is None
    assert parse_month("nope") is None
    assert parse_month(None) is None
    assert parse_month("2026-09") == (2026, 9)


def test_month_label_combines_the_german_month_name_and_year():
    assert month_label(2026, 9) == "September 2026"


def test_post_status_label_text():
    assert post_status_label(EventPostStatus.NONE) == "Kein Post"
    assert post_status_label(EventPostStatus.LINKED) == "Post verknüpft"
    assert post_status_label(EventPostStatus.DELIVERED) == "Post verknüpft · zugestellt ✓"


def test_filter_by_status_keeps_only_linked_or_only_unlinked_events():
    linked = make_view(make_event(datetime(2026, 9, 1, tzinfo=UTC)))
    linked.post_status = EventPostStatus.LINKED
    delivered = make_view(make_event(datetime(2026, 9, 2, tzinfo=UTC)))
    delivered.post_status = EventPostStatus.DELIVERED
    unlinked = make_view(make_event(datetime(2026, 9, 3, tzinfo=UTC)))

    views = [linked, delivered, unlinked]
    assert filter_by_status(views, "linked") == [linked, delivered]
    assert filter_by_status(views, "unlinked") == [unlinked]
    assert filter_by_status(views, "all") == views
    assert filter_by_status(views, "garbage") == views


def test_reason_label_text():
    assert reason_label(SuggestionReason.DATE) == "Datum steht im Text"
    assert reason_label(SuggestionReason.TITLE) == "Titel passt"
    assert reason_label(SuggestionReason.RECENT) == "Kurz vor dem Termin gepostet"
