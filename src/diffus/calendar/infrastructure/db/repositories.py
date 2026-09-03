"""SQLAlchemy implementations of the domain repository ports.

Repositories are bound to a unit of work: each one wraps a single AsyncSession
(see infrastructure/db/uow.py) and never opens or commits a transaction
itself — the surrounding CalendarUnitOfWork does that.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from diffus.calendar.domain.entities import CalendarEvent, EventLink, SubCalendar
from diffus.calendar.infrastructure.db.models import (
    EventPostRow,
    EventRow,
    EventSubCalendarRow,
    SubCalendarRow,
)


def _sub_calendar_to_row(sub_calendar: SubCalendar) -> dict:
    return {
        "id": sub_calendar.id,
        "name": sub_calendar.name,
        "color": sub_calendar.color,
        "position": sub_calendar.position,
    }


def _row_to_sub_calendar(row: SubCalendarRow) -> SubCalendar:
    return SubCalendar(id=row.id, name=row.name, color=row.color, position=row.position)


def _event_to_row(event: CalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "who": event.who,
        "location": event.location,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "whole_day": event.whole_day,
        "series_id": event.series_id,
        "removed_at": event.removed_at,
    }


def _row_to_event(row: EventRow, sub_calendar_ids: frozenset[int]) -> CalendarEvent:
    return CalendarEvent(
        id=row.id,
        title=row.title,
        description=row.description,
        who=row.who,
        location=row.location,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        whole_day=row.whole_day,
        sub_calendar_ids=sub_calendar_ids,
        series_id=row.series_id,
        removed_at=row.removed_at,
    )


def _row_to_link(row: EventPostRow) -> EventLink:
    return EventLink(event_id=row.event_id, post_id=row.post_id, linked_at=row.linked_at)


class SqlSubCalendarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save_all(self, sub_calendars: Sequence[SubCalendar]) -> None:
        if not sub_calendars:
            return
        stmt = pg_insert(SubCalendarRow).values(
            [_sub_calendar_to_row(sc) for sc in sub_calendars]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SubCalendarRow.id],
            set_={
                "name": stmt.excluded.name,
                "color": stmt.excluded.color,
                "position": stmt.excluded.position,
            },
        )
        await self._s.execute(stmt)

    async def list_all(self) -> list[SubCalendar]:
        result = await self._s.execute(
            select(SubCalendarRow).order_by(SubCalendarRow.position, SubCalendarRow.id)
        )
        return [_row_to_sub_calendar(row) for row in result.scalars().all()]


class SqlEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert_many(self, events: Sequence[CalendarEvent]) -> None:
        if not events:
            return
        stmt = pg_insert(EventRow).values([_event_to_row(e) for e in events])
        stmt = stmt.on_conflict_do_update(
            index_elements=[EventRow.id],
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "who": stmt.excluded.who,
                "location": stmt.excluded.location,
                "starts_at": stmt.excluded.starts_at,
                "ends_at": stmt.excluded.ends_at,
                "whole_day": stmt.excluded.whole_day,
                "series_id": stmt.excluded.series_id,
                "fetched_at": func.now(),
                "removed_at": None,
            },
        )
        await self._s.execute(stmt)

        ids = [e.id for e in events]
        await self._s.execute(
            delete(EventSubCalendarRow).where(EventSubCalendarRow.event_id.in_(ids))
        )

        pairs = [
            {"event_id": e.id, "sub_calendar_id": sub_calendar_id}
            for e in events
            for sub_calendar_id in e.sub_calendar_ids
        ]
        if pairs:
            await self._s.execute(insert(EventSubCalendarRow).values(pairs))

    async def mark_removed(
        self,
        window_start: datetime,
        window_end: datetime,
        seen_ids: Sequence[str],
        at: datetime,
    ) -> int:
        # An empty answer from the source is far more likely a hiccup than a
        # wiped calendar; the caller (SyncCalendar) already guards this, but
        # a bare NOT IN () would otherwise match every row in the window.
        if not seen_ids:
            return 0
        stmt = (
            update(EventRow)
            .where(
                EventRow.removed_at.is_(None),
                EventRow.starts_at >= window_start,
                EventRow.starts_at < window_end,
                EventRow.id.not_in(seen_ids),
            )
            .values(removed_at=at)
            # RETURNING instead of rowcount: same reasoning as SqlDeliveryRepository.claim,
            # so the count doesn't depend on a CursorResult-only attribute.
            .returning(EventRow.id)
        )
        result = await self._s.execute(stmt)
        return len(result.scalars().all())

    async def get(self, event_id: str) -> CalendarEvent | None:
        row = await self._s.get(EventRow, event_id)
        if row is None:
            return None
        grouped = await self._sub_calendar_ids([event_id])
        return _row_to_event(row, grouped.get(event_id, frozenset()))

    async def list_between(
        self, start: datetime, end: datetime, sub_calendar_ids: Sequence[int] = ()
    ) -> list[CalendarEvent]:
        stmt = select(EventRow).where(
            EventRow.removed_at.is_(None), EventRow.starts_at < end, EventRow.ends_at > start
        )
        if sub_calendar_ids:
            stmt = stmt.where(
                EventRow.id.in_(
                    select(EventSubCalendarRow.event_id).where(
                        EventSubCalendarRow.sub_calendar_id.in_(sub_calendar_ids)
                    )
                )
            )
        stmt = stmt.order_by(EventRow.starts_at, EventRow.id)
        rows = (await self._s.execute(stmt)).scalars().all()
        grouped = await self._sub_calendar_ids([row.id for row in rows])
        return [_row_to_event(row, grouped.get(row.id, frozenset())) for row in rows]

    async def _sub_calendar_ids(self, event_ids: Sequence[str]) -> dict[str, frozenset[int]]:
        if not event_ids:
            return {}
        result = await self._s.execute(
            select(EventSubCalendarRow.event_id, EventSubCalendarRow.sub_calendar_id).where(
                EventSubCalendarRow.event_id.in_(event_ids)
            )
        )
        grouped: dict[str, set[int]] = {}
        for event_id, sub_calendar_id in result.all():
            grouped.setdefault(event_id, set()).add(sub_calendar_id)
        return {event_id: frozenset(ids) for event_id, ids in grouped.items()}


class SqlEventLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, event_id: str, post_id: str) -> None:
        stmt = pg_insert(EventPostRow).values(event_id=event_id, post_id=post_id)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[EventPostRow.event_id, EventPostRow.post_id]
        )
        await self._s.execute(stmt)

    async def remove(self, event_id: str, post_id: str) -> None:
        await self._s.execute(
            delete(EventPostRow).where(
                EventPostRow.event_id == event_id, EventPostRow.post_id == post_id
            )
        )

    async def for_events(self, event_ids: Sequence[str]) -> dict[str, list[EventLink]]:
        if not event_ids:
            return {}
        result = await self._s.execute(
            select(EventPostRow).where(EventPostRow.event_id.in_(event_ids))
        )
        grouped: dict[str, list[EventLink]] = {}
        for row in result.scalars().all():
            grouped.setdefault(row.event_id, []).append(_row_to_link(row))
        return grouped
