"""Formatting for the calendar UI: German, human-scale, matching the crossposting style.

Pure functions that take `now`/`tz` explicitly so they are trivially testable.
Wired into Jinja as filters by presentation/routes.py.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import EventPostStatus, EventView
from diffus.calendar.application.suggest_posts import SuggestionReason
from diffus.calendar.domain.entities import CalendarEvent
from diffus.shared.presentation.display import MONTHS, WEEKDAYS


@dataclass(frozen=True, slots=True)
class GridDay:
    day: date
    in_month: bool
    is_today: bool
    events: tuple[EventView, ...]


@dataclass(frozen=True, slots=True)
class MonthGrid:
    year: int
    month: int
    label: str
    weeks: tuple[tuple[GridDay, ...], ...]
    prev: str
    next: str


def _day_month(day: date) -> str:
    return f"{day.day}. {MONTHS[day.month - 1]}"


def month_grid(
    views: Sequence[EventView], year: int, month: int, now: datetime, tz: ZoneInfo
) -> MonthGrid:
    """One 7-wide, calendar-month(ish) grid: an event occupies every local day it spans."""
    today = now.astimezone(tz).date()
    events_by_day: dict[date, list[EventView]] = {}
    for view in views:
        for day in view.event.local_days(tz):
            events_by_day.setdefault(day, []).append(view)

    weeks = tuple(
        tuple(
            GridDay(
                day=day,
                in_month=day.month == month,
                is_today=day == today,
                events=tuple(events_by_day.get(day, [])),
            )
            for day in week
        )
        for week in _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    )
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return MonthGrid(
        year=year,
        month=month,
        label=month_label(year, month),
        weeks=weeks,
        prev=f"{prev_year:04d}-{prev_month:02d}",
        next=f"{next_year:04d}-{next_month:02d}",
    )


def month_range(year: int, month: int) -> tuple[date, date]:
    """First visible Monday .. last visible Sunday (inclusive) of the grid for that month."""
    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    return weeks[0][0], weeks[-1][-1]


def by_day(
    views: Sequence[EventView], floor: date, tz: ZoneInfo
) -> list[tuple[date, list[EventView]]]:
    """Group events (already sorted by start) under their local start day, floored at `floor`.

    A running event that started before `floor` (e.g. the agenda's first
    visible day) is grouped under `floor` instead of its true start day.
    """
    grouped: dict[date, list[EventView]] = {}
    for view in views:
        start_day = view.event.starts_at.astimezone(tz).date()
        grouped.setdefault(max(start_day, floor), []).append(view)
    return list(grouped.items())


def format_agenda_day(day: date, now: datetime, tz: ZoneInfo) -> str:
    """'Heute · Donnerstag, 3. September' / 'Morgen · …' / 'Samstag, 5. September[ 2027]'."""
    today = now.astimezone(tz).date()
    text = f"{WEEKDAYS[day.weekday()]}, {_day_month(day)}"
    if day.year != today.year:
        text += f" {day.year}"
    if day == today:
        return f"Heute · {text}"
    if day == today + timedelta(days=1):
        return f"Morgen · {text}"
    return text


def format_event_time(event: CalendarEvent, tz: ZoneInfo) -> str:
    """'ganztägig' / 'ganztägig bis 29. August' / '18:00–20:00' / '16:00 – 11. Oktober, 15:00'."""
    if event.whole_day:
        days = event.local_days(tz)
        if len(days) == 1:
            return "ganztägig"
        return f"ganztägig bis {_day_month(days[-1])}"

    start = event.starts_at.astimezone(tz)
    end = event.ends_at.astimezone(tz)
    if start.date() == end.date():
        return f"{start:%H:%M}–{end:%H:%M}"
    return f"{start:%H:%M} – {_day_month(end.date())}, {end:%H:%M}"


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def parse_day(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_month(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    year_text, _, month_text = text.partition("-")
    if not (year_text.isdigit() and month_text.isdigit()):
        return None
    year, month = int(year_text), int(month_text)
    if not (1 <= month <= 12):
        return None
    return year, month


def post_status_label(status: EventPostStatus) -> str:
    return {
        EventPostStatus.NONE: "Kein Post",
        EventPostStatus.LINKED: "Post verknüpft",
        EventPostStatus.DELIVERED: "Post verknüpft · zugestellt ✓",
    }[status]


def reason_label(reason: SuggestionReason) -> str:
    return {
        SuggestionReason.DATE: "Datum steht im Text",
        SuggestionReason.TITLE: "Titel passt",
        SuggestionReason.RECENT: "Kurz vor dem Termin gepostet",
    }[reason]
