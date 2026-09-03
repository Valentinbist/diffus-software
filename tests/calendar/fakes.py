"""In-memory fakes implementing the calendar domain ports, for use-case unit tests.

No DB, no network. FakeCalendarUnitOfWork wires the three fake repositories
together the way SqlCalendarUnitOfWork wires the real ones. Every fake
repository's write methods set `dirty = True`; FakeCalendarUnitOfWork.__aexit__
raises if it is exited cleanly while any repository is still dirty, so a use
case that forgets to call commit() fails its test instead of silently passing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Self

from diffus.calendar.domain.entities import (
    CalendarEvent,
    CalendarSnapshot,
    EventLink,
    LinkablePost,
    SubCalendar,
)
from diffus.calendar.domain.ports import (
    EventLinkRepository,
    EventRepository,
    SubCalendarRepository,
)


class FakeCalendar:
    """CalendarGateway that returns a fixed snapshot and records the windows it was asked for."""

    def __init__(self, snapshot: CalendarSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[date, date]] = []

    async def fetch(self, start: date, end: date) -> CalendarSnapshot:
        self.calls.append((start, end))
        return self.snapshot


class FailingCalendar:
    """CalendarGateway that raises, the way KalenderDigitalClient does on an API error."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def fetch(self, start: date, end: date) -> CalendarSnapshot:
        raise self.error


class FakeSubCalendars:
    def __init__(self, sub_calendars: Sequence[SubCalendar] = ()) -> None:
        self._rows: dict[int, SubCalendar] = {sc.id: sc for sc in sub_calendars}
        self.dirty = False

    async def save_all(self, sub_calendars: Sequence[SubCalendar]) -> None:
        if not sub_calendars:
            return
        for sub_calendar in sub_calendars:
            self._rows[sub_calendar.id] = sub_calendar
        self.dirty = True

    async def list_all(self) -> list[SubCalendar]:
        return sorted(self._rows.values(), key=lambda sc: (sc.position, sc.id))


class FakeEvents:
    def __init__(self, events: Sequence[CalendarEvent] = ()) -> None:
        self._rows: dict[str, CalendarEvent] = {e.id: e for e in events}
        self.dirty = False

    async def upsert_many(self, events: Sequence[CalendarEvent]) -> None:
        if not events:
            return
        for event in events:
            self._rows[event.id] = dataclasses.replace(event, removed_at=None)
        self.dirty = True

    async def mark_removed(
        self,
        window_start: datetime,
        window_end: datetime,
        seen_ids: Sequence[str],
        at: datetime,
    ) -> int:
        if not seen_ids:
            return 0
        removed = 0
        for event_id, event in list(self._rows.items()):
            if (
                event.removed_at is None
                and window_start <= event.starts_at < window_end
                and event_id not in seen_ids
            ):
                self._rows[event_id] = dataclasses.replace(event, removed_at=at)
                removed += 1
        self.dirty = True
        return removed

    async def get(self, event_id: str) -> CalendarEvent | None:
        row = self._rows.get(event_id)
        return dataclasses.replace(row) if row is not None else None

    async def list_between(
        self, start: datetime, end: datetime, sub_calendar_ids: Sequence[int] = ()
    ) -> list[CalendarEvent]:
        wanted = set(sub_calendar_ids)
        matches = [
            event
            for event in self._rows.values()
            if event.removed_at is None
            and event.starts_at < end
            and event.ends_at > start
            and (not wanted or event.sub_calendar_ids & wanted)
        ]
        matches.sort(key=lambda e: (e.starts_at, e.id))
        return [dataclasses.replace(e) for e in matches]


class FakeEventLinks:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], EventLink] = {}
        self.dirty = False

    async def add(self, event_id: str, post_id: str) -> None:
        key = (event_id, post_id)
        if key not in self._rows:
            self._rows[key] = EventLink(
                event_id=event_id, post_id=post_id, linked_at=datetime.now(UTC)
            )
        self.dirty = True

    async def remove(self, event_id: str, post_id: str) -> None:
        self._rows.pop((event_id, post_id), None)
        self.dirty = True

    async def for_events(self, event_ids: Sequence[str]) -> dict[str, list[EventLink]]:
        grouped: dict[str, list[EventLink]] = {}
        for (event_id, _post_id), link in self._rows.items():
            if event_id in event_ids:
                grouped.setdefault(event_id, []).append(dataclasses.replace(link))
        return grouped


class FakeCalendarUnitOfWork:
    """CalendarUnitOfWork over the fake repositories, modelled on tests/crossposting/fakes.py."""

    def __init__(
        self,
        sub_calendars: FakeSubCalendars | None = None,
        events: FakeEvents | None = None,
        event_links: FakeEventLinks | None = None,
    ) -> None:
        # Kept as concrete types privately so __aexit__/commit/rollback can flip
        # `dirty`; exposed publicly at the Protocol type, like SqlCalendarUnitOfWork's
        # repositories, so ty checks use cases against the port, not the fake.
        self._sub_calendars = sub_calendars if sub_calendars is not None else FakeSubCalendars()
        self._events = events if events is not None else FakeEvents()
        self._event_links = event_links if event_links is not None else FakeEventLinks()
        self.sub_calendars: SubCalendarRepository = self._sub_calendars
        self.events: EventRepository = self._events
        self.event_links: EventLinkRepository = self._event_links
        self.commits = 0

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        dirty = self._sub_calendars.dirty or self._events.dirty or self._event_links.dirty
        try:
            if exc_type is None and dirty:
                raise AssertionError("unit of work exited with uncommitted writes")
        finally:
            self._clear_dirty()

    async def commit(self) -> None:
        self.commits += 1
        self._clear_dirty()

    async def rollback(self) -> None:
        self._clear_dirty()

    def _clear_dirty(self) -> None:
        self._sub_calendars.dirty = False
        self._events.dirty = False
        self._event_links.dirty = False


class FakePostCatalog:
    """PostCatalog with a fixed list of posts, indexed by id for by_ids()."""

    def __init__(self, posts: list[LinkablePost]) -> None:
        self.posts = posts

    async def recent(self, limit: int = 50) -> list[LinkablePost]:
        return list(self.posts)[:limit]

    async def by_ids(self, ids: Sequence[str]) -> dict[str, LinkablePost]:
        by_id = {post.id: post for post in self.posts}
        return {post_id: by_id[post_id] for post_id in ids if post_id in by_id}
