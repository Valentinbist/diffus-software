"""EventDirectory implemented over the calendar context's own read use cases and commands.

The sanctioned exception, the other way round from
calendar/infrastructure/crossposting.py: an adapter under a context's own
`infrastructure/` may call another context's `application/` use cases —
reads *and* commands, since the compose/publish wizard — because the
application layer of a context is its public API (see docs/architecture.md,
Bounded contexts). `GetLinkedEvents` and `GetComposeHint` are that public API
for reading events; `LinkEventPost.add` is the command half, called once a
wizard draft with an `event_ref` finishes publishing (see publish_draft.py).
`CreateEventForPost` is the command half of the unified wizard's Termin step
(round 4): this adapter now also carries event creation, mapping the
calendar's own EventPrefill/EventForm/SubCalendar to crossposting's own
mirrored types, and its ValueError/CalendarError to EventCreationError.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.application.compose_post import GetComposeHint
from diffus.calendar.application.create_event import CreateEventForPost, EventForm
from diffus.calendar.application.create_event import EventPrefill as CalendarEventPrefill
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent, SubCalendar
from diffus.calendar.domain.entities import ComposeHint as CalendarComposeHint
from diffus.calendar.domain.errors import CalendarError
from diffus.crossposting.domain.entities import (
    ComposeHint,
    EventFormOptions,
    EventPrefill,
    LinkedEvent,
    NewEventRequest,
    SubCalendarOption,
)
from diffus.crossposting.domain.errors import EventCreationError


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


def _to_event_prefill(prefill: CalendarEventPrefill) -> EventPrefill:
    return EventPrefill(
        title=prefill.title,
        day=prefill.day,
        start=prefill.start,
        end=prefill.end,
        whole_day=prefill.whole_day,
        description=prefill.description,
        sub_calendar_ids=prefill.sub_calendar_ids,
    )


def _to_sub_calendar_option(sub_calendar: SubCalendar) -> SubCalendarOption:
    return SubCalendarOption(id=sub_calendar.id, name=sub_calendar.name, color=sub_calendar.color)


@dataclass
class CalendarEventDirectory:
    linked: GetLinkedEvents
    hint: GetComposeHint
    link_post: LinkEventPost
    create_event_uc: CreateEventForPost

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

    async def event_form(self, post_id: str | None) -> EventFormOptions | None:
        result = await self.create_event_uc.prefill(post_id)
        if result is None:
            return None
        post, prefill, sub_calendars = result
        return EventFormOptions(
            prefill=_to_event_prefill(prefill),
            sub_calendars=tuple(_to_sub_calendar_option(sc) for sc in sub_calendars),
            post_id=post.id if post is not None else None,
        )

    async def create_event(self, request: NewEventRequest, post_id: str | None) -> LinkedEvent:
        form = EventForm(
            title=request.title,
            day=request.day,
            start=request.start,
            end=request.end,
            whole_day=request.whole_day,
            description=request.description,
            location=request.location,
            who=request.who,
            sub_calendar_ids=request.sub_calendar_ids,
        )
        try:
            event = await self.create_event_uc.create(post_id, form)
        except (ValueError, CalendarError) as exc:
            raise EventCreationError(str(exc)) from exc
        return _to_linked_event(event)
