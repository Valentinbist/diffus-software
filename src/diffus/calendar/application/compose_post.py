"""Caption template and compose hint for the crossposting compose wizard.

The event → post compose wizard itself (drafting, previewing, publishing)
moved into crossposting (`/posts/new`, round 3) — this module now only
supplies what crossposting needs to prefill it for an event: a caption
template (`caption_for_event`) and the read-only hint crossposting's
`EventDirectory.compose_hint` fetches (`GetComposeHint`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from diffus.calendar.domain.entities import CalendarEvent, ComposeHint, SubCalendar
from diffus.calendar.domain.ports import CalendarUnitOfWorkFactory
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
class GetComposeHint:
    """What the crossposting compose wizard (`/posts/new?event=<id>`) prefills for an event.

    A removed event can still get a post, so this includes removed events
    rather than 404ing — the event's own page already shows the "gelöscht"
    notice.
    """

    uow: CalendarUnitOfWorkFactory
    tz: ZoneInfo

    async def run(self, event_id: str) -> ComposeHint | None:
        async with self.uow() as uow:
            event = await uow.events.get(event_id)
            if event is None:
                return None
            sub_calendars = await uow.sub_calendars.list_all()
        return ComposeHint(
            event_id=event_id,
            title=event.title or "Ohne Titel",
            caption=caption_for_event(event, sub_calendars, self.tz),
            detail_url=f"/calendar/events/{event_id}",
        )
