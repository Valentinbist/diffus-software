"""Use case: the "link from a post" page — suggest events for one post, and list the rest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.suggest_posts import SuggestionReason, suggest_events
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost, SubCalendar
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory, PostCatalog


@dataclass
class LinkPickerEvent:
    event: CalendarEvent
    sub_calendars: list[SubCalendar]
    reasons: tuple[SuggestionReason, ...]
    linked: bool


@dataclass
class LinkPicker:
    post: LinkablePost
    suggestions: list[LinkPickerEvent]
    events: list[LinkPickerEvent]


def _resolve_sub_calendars(
    event: CalendarEvent, by_id: dict[int, SubCalendar]
) -> list[SubCalendar]:
    return sorted(
        (by_id[i] for i in event.sub_calendar_ids if i in by_id),
        key=lambda sc: (sc.position, sc.id),
    )


@dataclass
class GetLinkPicker:
    uow: CalendarUnitOfWorkFactory
    posts: PostCatalog
    tz: ZoneInfo
    window_days: int = 60

    async def run(self, post_id: str, now: datetime) -> LinkPicker | None:
        found = await self.posts.by_ids([post_id])
        if post_id not in found:
            return None
        post = found[post_id]

        window = timedelta(days=self.window_days)
        async with self.uow() as uow:
            sub_calendars = await uow.sub_calendars.list_all()
            events = await uow.events.list_between(now - window, now + window)
            links_by_post = await uow.event_links.for_posts([post_id])

        linked_ids = {link.event_id for link in links_by_post.get(post_id, [])}
        sc_by_id = {sc.id: sc for sc in sub_calendars}

        raw_suggestions = suggest_events(post, events, self.tz, limit=5)
        suggested_ids = {s.event_id for s in raw_suggestions}
        events_by_id = {e.id: e for e in events}

        suggestions = [
            LinkPickerEvent(
                event=events_by_id[s.event_id],
                sub_calendars=_resolve_sub_calendars(events_by_id[s.event_id], sc_by_id),
                reasons=s.reasons,
                linked=s.event_id in linked_ids,
            )
            for s in raw_suggestions
            if s.event_id in events_by_id
        ]
        remaining = [
            LinkPickerEvent(
                event=event,
                sub_calendars=_resolve_sub_calendars(event, sc_by_id),
                reasons=(),
                linked=event.id in linked_ids,
            )
            for event in events
            if event.id not in suggested_ids
        ]
        return LinkPicker(post=post, suggestions=suggestions, events=remaining)
