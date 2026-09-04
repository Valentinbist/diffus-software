"""Ports (protocols) the application layer depends on. Stdlib only.

Infrastructure adapters implement these protocols; the application layer
depends only on these abstractions, never on concrete infrastructure.

A CalendarUnitOfWork groups the repository writes of one use case into a
single persistence boundary: it never spans a network call. Writes commit
explicitly via `commit()`; reads never commit.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from types import TracebackType
from typing import Protocol, Self

from diffus.calendar.domain.entities import (
    CalendarEvent,
    CalendarSnapshot,
    DraftPreview,
    DraftRef,
    EventLink,
    LinkablePost,
    NewEvent,
    PublishedPost,
    PublishOptions,
    SubCalendar,
)


class CalendarGateway(Protocol):
    async def fetch(self, start: date, end: date) -> CalendarSnapshot: ...

    async def create_event(self, draft: NewEvent) -> CalendarEvent:
        """Writes a new event into the source and reads it back. Network, no unit of work."""
        ...


class PostPublisher(Protocol):
    """Composes and publishes a post via the crossposting context — see
    calendar/infrastructure/crossposting.py::CrosspostingPublisher, the adapter
    over crossposting's own drafting/publishing use cases (the sanctioned
    exception to "contexts never call each other's application layer", this
    time for a *command*, not just a read — see docs/architecture.md).
    """

    async def options(self) -> PublishOptions: ...

    async def create_draft(
        self, caption: str, uploads: Sequence[tuple[str, bytes]]
    ) -> DraftRef: ...

    async def get_draft(self, draft_id: str) -> DraftPreview | None: ...

    async def publish(
        self, draft_id: str, instagram: bool, telegram_addresses: Sequence[str]
    ) -> PublishedPost: ...

    async def discard(self, draft_id: str) -> None: ...


class PostCatalog(Protocol):
    """Read-only window onto the crossposting context's posts."""

    async def recent(self, limit: int = 50) -> list[LinkablePost]: ...

    async def by_ids(self, ids: Sequence[str]) -> dict[str, LinkablePost]: ...


class SubCalendarRepository(Protocol):
    async def save_all(self, sub_calendars: Sequence[SubCalendar]) -> None:
        """Upsert; never deletes a sub-calendar that stopped coming back."""
        ...

    async def list_all(self) -> list[SubCalendar]:
        """Ordered by position."""
        ...


class EventRepository(Protocol):
    async def upsert_many(self, events: Sequence[CalendarEvent]) -> None:
        """Clears removed_at on every upserted event and rewrites its sub-calendar rows."""
        ...

    async def mark_removed(
        self,
        window_start: datetime,
        window_end: datetime,
        seen_ids: Sequence[str],
        at: datetime,
    ) -> int:
        """Stamp removed_at on stored events in the window that weren't seen this sync."""
        ...

    async def get(self, event_id: str) -> CalendarEvent | None:
        """Removed events are included."""
        ...

    async def list_between(
        self, start: datetime, end: datetime, sub_calendar_ids: Sequence[int] = ()
    ) -> list[CalendarEvent]:
        """Overlap: starts_at < end AND ends_at > start; removed excluded.

        An empty sub_calendar_ids filter means all. Ordered by starts_at, id.
        """
        ...

    async def get_many(self, ids: Sequence[str]) -> dict[str, CalendarEvent]:
        """Removed events are included."""
        ...


class EventLinkRepository(Protocol):
    async def add(self, event_id: str, post_id: str) -> None:
        """Idempotent."""
        ...

    async def remove(self, event_id: str, post_id: str) -> None:
        """Idempotent."""
        ...

    async def for_events(self, event_ids: Sequence[str]) -> dict[str, list[EventLink]]: ...

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[EventLink]]:
        """A link is a fact: a removed event's own links still come back."""
        ...


class CalendarUnitOfWork(Protocol):
    sub_calendars: SubCalendarRepository
    events: EventRepository
    event_links: EventLinkRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


CalendarUnitOfWorkFactory = Callable[[], CalendarUnitOfWork]
