"""EventDirectory implemented over the calendar context's own read use cases.

The sanctioned exception, the other way round from
calendar/infrastructure/crossposting.py: an adapter under a context's own
`infrastructure/` may call another context's `application/` read use cases,
because the application read side of a context is its public API (see
docs/architecture.md, Bounded contexts). `GetLinkedEvents` is that public API
for events.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent
from diffus.crossposting.domain.entities import LinkedEvent


def _to_linked_event(event: CalendarEvent) -> LinkedEvent:
    return LinkedEvent(
        id=event.id,
        title=event.title,
        starts_at=event.starts_at,
        detail_url=f"/calendar/events/{event.id}",
        removed=event.removed,
    )


@dataclass
class CalendarEventDirectory:
    linked: GetLinkedEvents

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[LinkedEvent]]:
        events_by_post = await self.linked.for_posts(post_ids)
        return {
            post_id: [_to_linked_event(e) for e in events]
            for post_id, events in events_by_post.items()
        }
