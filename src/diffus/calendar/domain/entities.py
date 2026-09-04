"""Core domain entities and value objects. Stdlib only — no external dependencies allowed here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
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


@dataclass(frozen=True, slots=True)
class NewEvent:
    """An event the compose-an-event wizard is about to write into kalender.digital.

    UTC, exclusive end — the same convention CalendarEvent uses. Not yet a
    CalendarEvent (no id, no series_id) because kalender.digital assigns
    those; CalendarGateway.create_event turns one of these into a real
    CalendarEvent by writing it and reading the result back.
    """

    title: str
    description: str | None
    who: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    whole_day: bool
    sub_calendar_ids: frozenset[int]


# -- Post publishing (compose-a-post wizard) --------------------------------
#
# The calendar's own tiny read model of the crossposting context's drafts and
# publish options, via the PostPublisher port (calendar/infrastructure/crossposting.py
# is the adapter). Mirrors how LinkablePost is the calendar's view of a Post.


@dataclass(frozen=True, slots=True)
class DraftRef:
    id: str


@dataclass(frozen=True, slots=True)
class DraftPreview:
    id: str
    caption: str
    image_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TelegramTarget:
    address: str
    label: str


class InstagramState(StrEnum):
    READY = "ready"
    NOT_CONNECTED = "not_connected"
    NO_PUBLISH_SCOPE = "no_publish_scope"
    NO_PUBLIC_URL = "no_public_url"


@dataclass(frozen=True, slots=True)
class PublishOptions:
    instagram: InstagramState
    targets: tuple[TelegramTarget, ...]


@dataclass(frozen=True, slots=True)
class PublishedPost:
    id: str
    permalink: str
    detail_url: str
