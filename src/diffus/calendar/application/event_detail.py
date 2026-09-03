"""Use case: everything the event page shows — the event, its links, and post suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import EventView, build_event_views
from diffus.calendar.application.suggest_posts import SuggestionReason, suggest_posts
from diffus.calendar.domain.entities import LinkablePost
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory, PostCatalog


@dataclass
class SuggestedPost:
    post: LinkablePost
    reasons: tuple[SuggestionReason, ...]


@dataclass
class EventDetail:
    view: EventView
    linked: list[LinkablePost]
    suggestions: list[SuggestedPost]
    recent: list[LinkablePost]


@dataclass
class GetEventDetail:
    uow: CalendarUnitOfWorkFactory
    posts: PostCatalog
    tz: ZoneInfo
    candidates: int = 50

    async def run(self, event_id: str) -> EventDetail | None:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)  # removed events are included
            if event is None:
                return None
            sub_calendars = await uow.sub_calendars.list_all()
            links_by_event = await uow.event_links.for_events([event_id])
        links = links_by_event.get(event_id, [])

        linked_by_id = await self.posts.by_ids([link.post_id for link in links])
        # Link order, not lookup order; a post the crossposting side no longer knows is skipped.
        linked = [linked_by_id[link.post_id] for link in links if link.post_id in linked_by_id]

        pool = [p for p in await self.posts.recent(self.candidates) if p.id not in linked_by_id]
        raw_suggestions = suggest_posts(event, pool, self.tz)
        pool_by_id = {p.id: p for p in pool}
        suggestions = [
            SuggestedPost(post=pool_by_id[s.post_id], reasons=s.reasons) for s in raw_suggestions
        ]
        suggested_ids = {s.post_id for s in raw_suggestions}
        recent = [p for p in pool if p.id not in suggested_ids]

        view = build_event_views([event], sub_calendars, {event_id: links}, linked_by_id)[0]
        return EventDetail(view=view, linked=linked, suggestions=suggestions, recent=recent)
