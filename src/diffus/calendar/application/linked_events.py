"""Use case: which calendar events are linked to a given set of posts.

The read side behind crossposting's index/post pages — see
crossposting/infrastructure/calendar.py, the adapter that calls this.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.domain.entities import CalendarEvent
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory


@dataclass
class GetLinkedEvents:
    uow: CalendarUnitOfWorkFactory

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[CalendarEvent]]:
        async with self.uow() as uow:
            links_by_post = await uow.event_links.for_posts(post_ids)
            event_ids = {link.event_id for links in links_by_post.values() for link in links}
            events_by_id = await uow.events.get_many(list(event_ids))

        result: dict[str, list[CalendarEvent]] = {}
        for post_id, links in links_by_post.items():
            events = [
                events_by_id[link.event_id] for link in links if link.event_id in events_by_id
            ]
            events.sort(key=lambda e: e.starts_at)
            result[post_id] = events
        return result
