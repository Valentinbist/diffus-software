"""EventDirectory implemented over the calendar context's own read use cases and commands.

The sanctioned exception, the other way round from
calendar/infrastructure/crossposting.py: an adapter under a context's own
`infrastructure/` may call another context's `application/` use cases —
reads *and* commands, since the compose/publish wizard — because the
application layer of a context is its public API (see docs/architecture.md,
Bounded contexts). `GetLinkedEvents` and `GetComposeHint` are that public API
for reading events; `LinkEventPost.add` is the command half, called once a
wizard draft with an `event_ref` finishes publishing (see publish_draft.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.application.compose_post import GetComposeHint
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent
from diffus.calendar.domain.entities import ComposeHint as CalendarComposeHint
from diffus.crossposting.domain.entities import ComposeHint, LinkedEvent


def _to_linked_event(event: CalendarEvent) -> LinkedEvent:
    return LinkedEvent(
        id=event.id,
        title=event.title,
        starts_at=event.starts_at,
        detail_url=f"/calendar/events/{event.id}",
        removed=event.removed,
    )


def _to_compose_hint(hint: CalendarComposeHint) -> ComposeHint:
    return ComposeHint(
        event_id=hint.event_id,
        title=hint.title,
        caption=hint.caption,
        detail_url=hint.detail_url,
    )


@dataclass
class CalendarEventDirectory:
    linked: GetLinkedEvents
    hint: GetComposeHint
    link_post: LinkEventPost

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[LinkedEvent]]:
        events_by_post = await self.linked.for_posts(post_ids)
        return {
            post_id: [_to_linked_event(e) for e in events]
            for post_id, events in events_by_post.items()
        }

    async def compose_hint(self, event_id: str) -> ComposeHint | None:
        hint = await self.hint.run(event_id)
        return _to_compose_hint(hint) if hint is not None else None

    async def link(self, event_id: str, post_id: str) -> None:
        await self.link_post.add(event_id, post_id)
