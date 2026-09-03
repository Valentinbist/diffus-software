"""Core domain entities and value objects. Stdlib only — no external dependencies allowed here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class SubCalendar:
    id: int
    name: str
    color: str  # "#31859B"; the adapter validates, fallback "#4C4C4C"
    position: int  # order the source lists them in


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str  # kalender.digital id, stable per occurrence
    title: str  # "" when untitled
    description: str | None
    who: str | None
    location: str | None
    starts_at: datetime  # UTC, aware
    ends_at: datetime  # UTC, aware, exclusive
    whole_day: bool
    sub_calendar_ids: frozenset[int]
    series_id: int | None
    removed_at: datetime | None = None

    @property
    def removed(self) -> bool:
        return self.removed_at is not None

    def local_days(self, tz: ZoneInfo) -> list[date]:
        """Every local calendar day the half-open [starts_at, ends_at) interval touches.

        An event ending exactly at local midnight does not include that day
        (the interval is exclusive at the end); a zero-length event yields
        just its start day.
        """
        start_day = self.starts_at.astimezone(tz).date()
        end_local = self.ends_at.astimezone(tz)
        end_day = end_local.date()
        if end_local.time() == time.min and end_day > start_day:
            end_day -= timedelta(days=1)
        if end_day < start_day:
            end_day = start_day

        days = []
        day = start_day
        while day <= end_day:
            days.append(day)
            day += timedelta(days=1)
        return days

    def is_on(self, day: date, tz: ZoneInfo) -> bool:
        return day in self.local_days(tz)


@dataclass(frozen=True, slots=True)
class CalendarSnapshot:
    sub_calendars: tuple[SubCalendar, ...]
    events: tuple[CalendarEvent, ...]


@dataclass(frozen=True, slots=True)
class EventLink:
    event_id: str
    post_id: str
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class LinkablePost:
    """The calendar's own view of a post from the crossposting context (via PostCatalog)."""

    id: str
    caption: str | None
    permalink: str
    posted_at: datetime
    thumbnail_url: str | None  # a URL the browser can load: stored preview route or CDN
    detail_url: str  # e.g. "/posts/<id>"
    delivered: bool  # at least one destination received it
