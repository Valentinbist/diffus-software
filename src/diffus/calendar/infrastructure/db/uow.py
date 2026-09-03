"""The only place this context opens a database session.

SqlCalendarUnitOfWork binds one AsyncSession's worth of repositories together
so a use case can group several writes into one persistence boundary: a unit
of work never spans a network call. `commit()` is explicit; `__aexit__`
always rolls back (a no-op after a successful commit) and closes the session.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diffus.calendar.infrastructure.db.repositories import (
    SqlEventLinkRepository,
    SqlEventRepository,
    SqlSubCalendarRepository,
)


class SqlCalendarUnitOfWork:
    sub_calendars: SqlSubCalendarRepository
    events: SqlEventRepository
    event_links: SqlEventLinkRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._sf()
        self.sub_calendars = SqlSubCalendarRepository(self._session)
        self.events = SqlEventRepository(self._session)
        self.event_links = SqlEventLinkRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
