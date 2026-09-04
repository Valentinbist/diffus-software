"""Use case: the event → post compose wizard.

Two requests, mirroring the crossposting drafting flow this rides on top of:
`prefill` shows a caption template + upload form, `start` turns the upload
into a draft, `preview` shows what will be published, and `publish` hands
off to the PostPublisher and — the one write this use case itself owns —
links the resulting post back to the event.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import EventView, build_event_views
from diffus.calendar.domain.entities import (
    CalendarEvent,
    DraftPreview,
    PublishedPost,
    PublishOptions,
    SubCalendar,
)
from diffus.calendar.domain.errors import UnknownEventError
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory, PostCatalog, PostPublisher
from diffus.shared.dates import MONTHS, WEEKDAYS

LOCATION = "Viktoriastraße 18"


def _weekday_day_month(day: date) -> str:
    """`day` may be a plain date or an aware datetime — both have weekday()/day/month."""
    return f"{WEEKDAYS[day.weekday()]}, {day.day}. {MONTHS[day.month - 1]}"


def _resolve_rooms(event: CalendarEvent, sub_calendars: Sequence[SubCalendar]) -> list[SubCalendar]:
    by_id = {sc.id: sc for sc in sub_calendars}
    return sorted(
        (by_id[i] for i in event.sub_calendar_ids if i in by_id),
        key=lambda sc: (sc.position, sc.id),
    )


def _date_line(event: CalendarEvent, tz: ZoneInfo) -> str:
    if event.whole_day:
        days = event.local_days(tz)
        if len(days) == 1:
            return f"📅 {_weekday_day_month(days[0])}"
        return f"📅 {_weekday_day_month(days[0])} – {_weekday_day_month(days[-1])}"

    start = event.starts_at.astimezone(tz)
    end = event.ends_at.astimezone(tz)
    if start.date() == end.date():
        return f"📅 {_weekday_day_month(start)} · {start:%H:%M}–{end:%H:%M} Uhr"
    end_part = f"{_weekday_day_month(end)}, {end:%H:%M} Uhr"
    return f"📅 {_weekday_day_month(start)} · {start:%H:%M} – {end_part}"


def _location_line(event: CalendarEvent, rooms: Sequence[SubCalendar]) -> str:
    location = event.location or LOCATION
    if not rooms:
        return f"📍 {location}"
    return f"📍 {location}, {', '.join(sc.name for sc in rooms)}"


def caption_for_event(
    event: CalendarEvent, sub_calendars: Sequence[SubCalendar], tz: ZoneInfo
) -> str:
    """The prefilled caption template for a compose-a-post wizard, in the exact shape
    the owner asked for: title, then a date/time line, then a location line, then a
    blank line and the event's own description (omitted entirely when there is none)."""
    title = event.title or "Ohne Titel"
    rooms = _resolve_rooms(event, sub_calendars)
    lines = [title, _date_line(event, tz), _location_line(event, rooms)]
    caption = "\n".join(lines)
    if event.description:
        caption += f"\n\n{event.description}"
    return caption


@dataclass
class ComposePrefill:
    caption: str


@dataclass
class ComposeForm:
    view: EventView
    prefill: ComposePrefill
    options: PublishOptions


@dataclass
class ComposePreview:
    view: EventView
    draft: DraftPreview
    options: PublishOptions


@dataclass
class ComposePostForEvent:
    uow: CalendarUnitOfWorkFactory
    publisher: PostPublisher
    posts: PostCatalog
    tz: ZoneInfo

    async def _view(self, event_id: str) -> EventView | None:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)  # removed events can still get a post
            if event is None:
                return None
            sub_calendars = await uow.sub_calendars.list_all()
            links_by_event = await uow.event_links.for_events([event_id])
        links = links_by_event.get(event_id, [])
        posts_by_id = await self.posts.by_ids([link.post_id for link in links])
        return build_event_views([event], sub_calendars, {event_id: links}, posts_by_id)[0]

    async def prefill(self, event_id: str) -> ComposeForm | None:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)
            if event is None:
                return None
            sub_calendars = await uow.sub_calendars.list_all()
            links_by_event = await uow.event_links.for_events([event_id])
        links = links_by_event.get(event_id, [])
        posts_by_id = await self.posts.by_ids([link.post_id for link in links])
        view = build_event_views([event], sub_calendars, {event_id: links}, posts_by_id)[0]

        options = await self.publisher.options()
        caption = caption_for_event(event, sub_calendars, self.tz)
        return ComposeForm(view=view, prefill=ComposePrefill(caption=caption), options=options)

    async def start(
        self, event_id: str, caption: str, uploads: Sequence[tuple[str, bytes]]
    ) -> str:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)
        if event is None:
            raise UnknownEventError(event_id)

        draft = await self.publisher.create_draft(caption, uploads)
        return draft.id

    async def preview(self, event_id: str, draft_id: str) -> ComposePreview | None:
        view = await self._view(event_id)
        if view is None:
            return None
        draft = await self.publisher.get_draft(draft_id)
        if draft is None:
            return None
        options = await self.publisher.options()
        return ComposePreview(view=view, draft=draft, options=options)

    async def publish(
        self, event_id: str, draft_id: str, instagram: bool, addresses: Sequence[str]
    ) -> PublishedPost:
        published = await self.publisher.publish(draft_id, instagram, addresses)
        async with self.uow() as uow:
            await uow.event_links.add(event_id, published.id)
            await uow.commit()
        return published

    async def discard(self, draft_id: str) -> None:
        await self.publisher.discard(draft_id)
