"""Use case: link and unlink a post to an event."""

from __future__ import annotations

from dataclasses import dataclass

from diffus.calendar.domain.errors import UnknownEventError, UnknownPostError
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory, PostCatalog


@dataclass
class LinkEventPost:
    uow: CalendarUnitOfWorkFactory
    posts: PostCatalog

    async def add(self, event_id: str, post_id: str) -> None:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)  # removed events can still be linked
        if event is None:
            raise UnknownEventError(event_id)

        found = await self.posts.by_ids([post_id])
        if post_id not in found:
            raise UnknownPostError(post_id)

        async with self.uow() as uow:
            await uow.event_links.add(event_id, post_id)
            await uow.commit()

    async def remove(self, event_id: str, post_id: str) -> None:
        async with self.uow() as uow:
            await uow.event_links.remove(event_id, post_id)
            await uow.commit()
