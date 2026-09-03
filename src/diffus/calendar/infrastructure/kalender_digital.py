"""kalender.digital adapter: implements CalendarGateway.

This talks to the JSON API kalender.digital's own Angular web app uses. It is
undocumented, but the calendar's documented ICS export
(`https://export.kalender.digital/ics/{subCalendarId}/{token}/{slug}.ics`,
with each VEVENT's UID formatted `KDIG{id}`) shares this API's event ids, so
an `IcsCalendarGateway` reading that feed instead is a drop-in fallback
behind the same `CalendarGateway` port if this API ever goes away.

The share-link token (`capabilityId`) is an editor-level credential: anyone
holding it can edit or delete the whole calendar. Never log request URLs —
they carry it as a query parameter (see also `_SECRET_PATTERNS` in
shared/presentation/display.py, which redacts it from rendered error text).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx

from diffus.calendar.domain.entities import CalendarEvent, CalendarSnapshot, SubCalendar

API_BASE = "https://api.kalender.digital"
FALLBACK_COLOR = "#4C4C4C"
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class KalenderDigitalClient:
    def __init__(self, http: httpx.AsyncClient, *, token: str, api_base: str = API_BASE) -> None:
        self.http = http
        self.token = token
        self.api_base = api_base

    async def fetch(self, start: date, end: date) -> CalendarSnapshot:
        resp = await self.http.get(
            f"{self.api_base}/calendar", params={"capabilityId": self.token}
        )
        resp.raise_for_status()
        payload = resp.json()
        # The source's own zone, not the UI's display timezone: whole-day
        # events and local-time parsing below both need the calendar's zone.
        tz = ZoneInfo(payload.get("timeZone") or "Europe/Berlin")

        events_resp = await self.http.get(
            f"{self.api_base}/event",
            params={
                "capabilityId": self.token,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "timeZone": tz.key,
            },
        )
        events_resp.raise_for_status()

        return CalendarSnapshot(
            sub_calendars=self._parse_sub_calendars(payload),
            events=self._parse_events(events_resp.json(), tz),
        )

    @classmethod
    def _parse_sub_calendars(cls, payload: dict) -> tuple[SubCalendar, ...]:
        sub_calendars: list[SubCalendar] = []
        for position, entry in enumerate(payload.get("subCalendars") or []):
            raw_id = entry.get("id")
            name = entry.get("name")
            if raw_id is None or not name:
                continue
            color = entry.get("color") or ""
            if not _COLOR.match(color):
                color = FALLBACK_COLOR
            sub_calendars.append(
                SubCalendar(id=int(raw_id), name=name, color=color, position=position)
            )
        return tuple(sub_calendars)

    @classmethod
    def _parse_events(cls, payload: list, tz: ZoneInfo) -> tuple[CalendarEvent, ...]:
        events: list[CalendarEvent] = []
        for item in payload:
            raw_id = item.get("id")
            start_text = item.get("start_date")
            if raw_id is None or not start_text:
                continue

            starts_at = datetime.fromisoformat(start_text).replace(tzinfo=tz).astimezone(UTC)
            end_text = item.get("end_date")
            ends_at = (
                datetime.fromisoformat(end_text).replace(tzinfo=tz).astimezone(UTC)
                if end_text
                else starts_at
            )
            # The API's end is already exclusive (whole-day events end at
            # 00:00 the following day) — never add a day here.
            if ends_at <= starts_at:
                ends_at = starts_at

            events.append(
                CalendarEvent(
                    id=str(raw_id),
                    title=item.get("title") or "",
                    description=item.get("text") or None,
                    who=item.get("who") or None,
                    location=item.get("where") or None,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    whole_day=bool(item.get("wholeDay")),
                    sub_calendar_ids=frozenset(int(x) for x in item.get("subCalendars") or []),
                    series_id=item.get("repeatSeriesId"),
                )
            )
        return tuple(events)
