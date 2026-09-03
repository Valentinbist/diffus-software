"""Use case: the calendar's read side — agenda list and month grid share this query."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from diffus.calendar.domain.entities import CalendarEvent, EventLink, LinkablePost, SubCalendar
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory, PostCatalog


class EventPostStatus(StrEnum):
    NONE = "none"
    LINKED = "linked"
    DELIVERED = "delivered"


@dataclass
class EventView:
    event: CalendarEvent
    sub_calendars: list[SubCalendar]
    links: list[EventLink]
    post_status: EventPostStatus


@dataclass
class CalendarPage:
    sub_calendars: list[SubCalendar]
    events: list[EventView]


def post_status(
    links: Sequence[EventLink], posts_by_id: Mapping[str, LinkablePost]
) -> EventPostStatus:
    if not links:
        return EventPostStatus.NONE
    if any(posts_by_id[link.post_id].delivered for link in links if link.post_id in posts_by_id):
        return EventPostStatus.DELIVERED
    return EventPostStatus.LINKED


def build_event_views(
    events: Sequence[CalendarEvent],
    sub_calendars: Sequence[SubCalendar],
    links_by_event: Mapping[str, list[EventLink]],
    posts_by_id: Mapping[str, LinkablePost],
) -> list[EventView]:
    by_id = {sc.id: sc for sc in sub_calendars}
    views = []
    for event in events:
        links = links_by_event.get(event.id, [])
        resolved = sorted(
            (by_id[i] for i in event.sub_calendar_ids if i in by_id),
            key=lambda sc: (sc.position, sc.id),
        )
        views.append(
            EventView(
                event=event,
                sub_calendars=resolved,
                links=links,
                post_status=post_status(links, posts_by_id),
            )
        )
    return views


@dataclass
class GetCalendarEvents:
    uow: CalendarUnitOfWorkFactory
    posts: PostCatalog
    tz: ZoneInfo

    async def run(
        self, start_day: date, end_day: date, sub_calendar_ids: Sequence[int] = ()
    ) -> CalendarPage:
        start = datetime.combine(start_day, time.min, tzinfo=self.tz).astimezone(UTC)
        end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=self.tz).astimezone(
            UTC
        )
        async with self.uow() as uow:
            sub_calendars = await uow.sub_calendars.list_all()
            events = await uow.events.list_between(start, end, sub_calendar_ids)
            links_by_event = await uow.event_links.for_events([e.id for e in events])

        post_ids = sorted({link.post_id for links in links_by_event.values() for link in links})
        posts_by_id = await self.posts.by_ids(post_ids)

        views = build_event_views(events, sub_calendars, links_by_event, posts_by_id)
        return CalendarPage(sub_calendars=sub_calendars, events=views)
