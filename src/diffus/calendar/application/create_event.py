"""Use case: the post → event wizard. Writes a new event into kalender.digital and links it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.caption_dates import find_date_mentions, resolve_mention
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost, NewEvent, SubCalendar
from diffus.calendar.domain.errors import UnknownPostError
from diffus.calendar.domain.ports import CalendarGateway, CalendarUnitOfWorkFactory, PostCatalog

# "Öffentliche Veranstaltung" on the shared kalender.digital calendar — the
# sub-calendar most posts should land in by default; a post-specific choice
# always overrides it, and it's silently dropped if the calendar ever stops
# listing that id (see CreateEventForPost.prefill).
DEFAULT_SUB_CALENDAR_IDS = frozenset({5298948})


def _title_from_caption(caption: str | None, limit: int = 60) -> str:
    """First non-empty caption line, cut to `limit` characters — the compose form's own
    default title. Duplicated from shared.presentation.display.summary() on purpose: the
    calendar's application layer never imports a presentation module (see docs/architecture.md)."""
    if not caption:
        return ""
    line = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    if len(line) <= limit:
        return line
    return line[: limit - 1].rstrip() + "…"


@dataclass
class EventPrefill:
    title: str
    day: date
    description: str
    sub_calendar_ids: frozenset[int]
    start: time = time(18, 0)
    end: time = time(22, 0)
    whole_day: bool = False


@dataclass
class EventForm:
    title: str
    day: date
    start: time
    end: time
    whole_day: bool
    description: str
    location: str
    who: str
    sub_calendar_ids: frozenset[int]


@dataclass
class CreateEventForPost:
    uow: CalendarUnitOfWorkFactory
    posts: PostCatalog
    calendar: CalendarGateway
    tz: ZoneInfo
    default_sub_calendar_ids: frozenset[int] = DEFAULT_SUB_CALENDAR_IDS

    async def prefill(
        self, post_id: str | None
    ) -> tuple[LinkablePost | None, EventPrefill, list[SubCalendar]] | None:
        if post_id is None:
            async with self.uow() as uow:
                sub_calendars = await uow.sub_calendars.list_all()
            existing_ids = {sc.id for sc in sub_calendars}
            default_ids = frozenset(i for i in self.default_sub_calendar_ids if i in existing_ids)
            prefill = EventPrefill(
                title="",
                day=datetime.now(UTC).astimezone(self.tz).date(),
                description="",
                sub_calendar_ids=default_ids,
            )
            return None, prefill, sub_calendars

        found = await self.posts.by_ids([post_id])
        if post_id not in found:
            return None
        post = found[post_id]

        posted_day = post.posted_at.astimezone(self.tz).date()
        day = posted_day
        for mention in find_date_mentions(post.caption):
            resolved = resolve_mention(mention, around=posted_day)
            if resolved is not None:
                day = resolved
                break

        async with self.uow() as uow:
            sub_calendars = await uow.sub_calendars.list_all()
        existing_ids = {sc.id for sc in sub_calendars}
        default_ids = frozenset(i for i in self.default_sub_calendar_ids if i in existing_ids)

        prefill = EventPrefill(
            title=_title_from_caption(post.caption),
            day=day,
            description=post.caption or "",
            sub_calendar_ids=default_ids,
        )
        return post, prefill, sub_calendars

    async def create(self, post_id: str | None, form: EventForm) -> CalendarEvent:
        if post_id:
            found = await self.posts.by_ids([post_id])
            if post_id not in found:
                raise UnknownPostError(post_id)

        if form.whole_day:
            start_local = datetime.combine(form.day, time.min, tzinfo=self.tz)
            end_local = datetime.combine(form.day + timedelta(days=1), time.min, tzinfo=self.tz)
        else:
            if form.end <= form.start:
                raise ValueError("Das Ende muss nach dem Beginn liegen.")
            start_local = datetime.combine(form.day, form.start, tzinfo=self.tz)
            end_local = datetime.combine(form.day, form.end, tzinfo=self.tz)

        draft = NewEvent(
            title=form.title,
            description=form.description or None,
            who=form.who or None,
            location=form.location or None,
            starts_at=start_local.astimezone(UTC),
            ends_at=end_local.astimezone(UTC),
            whole_day=form.whole_day,
            sub_calendar_ids=form.sub_calendar_ids,
        )
        event = await self.calendar.create_event(draft)  # network, outside any unit of work

        async with self.uow() as uow:
            await uow.events.upsert_many([event])
            if post_id:
                await uow.event_links.add(event.id, post_id)
            await uow.commit()
        return event
