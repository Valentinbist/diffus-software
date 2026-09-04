"""Typed home for everything a calendar route needs from the composition root.

Mirrors diffus.crossposting.presentation.services.Services: one frozen
dataclass, built once by the composition root (diffus/app.py) — or directly
from fakes in tests — and handed to routes through get_calendar_services.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from diffus.calendar.application.calendar_events import GetCalendarEvents
from diffus.calendar.application.create_event import CreateEventForPost
from diffus.calendar.application.event_detail import GetEventDetail
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.link_picker import GetLinkPicker
from diffus.calendar.application.sync_job import CalendarSyncJob


@dataclass(frozen=True, slots=True)
class CalendarServices:
    sync_job: CalendarSyncJob
    calendar: GetCalendarEvents
    event_detail: GetEventDetail
    link_post: LinkEventPost
    link_picker: GetLinkPicker
    create_event: CreateEventForPost
    tz: ZoneInfo
    templates: Jinja2Templates


def get_calendar_services(request: Request) -> CalendarServices:
    services = request.app.state.calendar
    if services is None:
        raise HTTPException(status_code=404, detail="calendar not configured")
    return services
