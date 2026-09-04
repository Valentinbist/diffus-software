"""Mock of kalender.digital's undocumented JSON API, the surface `KalenderDigitalClient` calls.

Stands in for `https://api.kalender.digital`, mounted here at `/kalender`:

- `GET /kalender/calendar?capabilityId` — the calendar + its sub-calendars
- `GET /kalender/event?capabilityId&startDate&endDate&timeZone` — events in
  a date window
- `POST /kalender/event?timeZone=` — create an event
- `GET /kalender/event/{id}?capabilityId&timeZone` — one event
- `PUT`/`DELETE /kalender/event/{id}` — for completeness; not called by
  `KalenderDigitalClient` today

`capabilityId` (the share-link token) is checked on every call — query
param for the GETs, JSON body field for the POST — exactly like the real
share-link permission model; a wrong or missing one gets the real API's own
`{"msg": "FAILURE_NO_ACCESS"}` shape.

Seeded relative to *today* (not a fixed date) so the agenda is never empty
regardless of when the mock stack is started: a weekly "Stammtisch" and a
weekly "Plenum", a one-day and a two-day whole-day event, a one-off event on
the 12th of next month (loosely matching the Instagram mock's seeded
caption (the same date, via mocks/dates.py), for the link-suggestion heuristic to
have something to find), and one event crossing midnight.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from mocks.dates import siebdruck_day

DEFAULT_TOKEN = "mock-token"
TOKEN_ENV = "MOCK_KALENDER_TOKEN"
CALENDAR_ID = 48963
TIME_ZONE = "Europe/Berlin"

# The association's real sub-calendars (ids/colours/names taken from the
# recorded payloads pinning KalenderDigitalClient's tests), extended to the
# full 7 the real calendar has.
SUB_CALENDARS = [
    # The seven real sub-calendars of the shared room calendar, ids, names and
    # colours as kalender.digital returns them (recorded 2026-09-03).
    {"id": 472104, "name": "Haupt-Raum", "color": "#31859B"},
    {"id": 472105, "name": "Werkstatt-Raum", "color": "#8064A2"},
    {"id": 472114, "name": "Innenhof", "color": "#4F81BD"},
    {"id": 5298948, "name": "Öffentliche Veranstaltung", "color": "#9BBB59"},
    {"id": 5298949, "name": "Do not disturb!", "color": "#F79646"},
    {"id": 5687603, "name": "Sonstiges/Ausleihen (Keine Raumbuchung)", "color": "#938953"},
    {"id": 6001525, "name": "ZweiterPlenumsRaum", "color": "#FF0000"},
]

NO_ACCESS = {"msg": "FAILURE_NO_ACCESS"}


@dataclass
class Event:
    id: int
    title: str
    starts_at: datetime  # UTC, aware
    ends_at: datetime  # UTC, aware, exclusive
    text: str = ""
    who: str = ""
    where: str = ""
    sub_calendars: list[int] = field(default_factory=list)
    whole_day: bool = False
    repeat_series_id: int | None = None
    repeat_interval: int = 0
    imported: bool = False
    has_reminder: bool = False
    has_registration: bool = False


def _weekday_on_or_after(day: date, weekday: int, *, strictly_after: bool = False) -> date:
    ahead = (weekday - day.weekday()) % 7
    if ahead == 0 and strictly_after:
        ahead = 7
    return day + timedelta(days=ahead)


def _local(day: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, t, tzinfo=tz).astimezone(UTC)


@dataclass
class State:
    token: str = DEFAULT_TOKEN
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(TIME_ZONE))
    events: dict[int, Event] = field(default_factory=dict)
    next_id: int = 9_000_000_001

    def seed(self) -> None:
        self.events.clear()
        self.next_id = 9_000_000_001
        today = datetime.now(self.tz).date()
        tz = self.tz

        # Weekly Stammtisch, Wed 19:00-22:00, -8..+12 weeks, one series id.
        stammtisch_anchor = _weekday_on_or_after(today, 2)  # Wednesday
        series_id = 555_000_001
        for week in range(-8, 13):
            day = stammtisch_anchor + timedelta(weeks=week)
            self.add_event(
                title="Stammtisch",
                starts_at=_local(day, time(19, 0), tz),
                ends_at=_local(day, time(22, 0), tz),
                sub_calendars=[472104, 5298948],
                repeat_series_id=series_id,
                repeat_interval=1,
            )

        # Weekly Plenum, Mon 18:00-22:00, -8..+12 weeks, its own series id.
        plenum_anchor = _weekday_on_or_after(today, 0)  # Monday
        plenum_series_id = 555_000_002
        for week in range(-8, 13):
            day = plenum_anchor + timedelta(weeks=week)
            self.add_event(
                title="Plenum",
                starts_at=_local(day, time(18, 0), tz),
                ends_at=_local(day, time(22, 0), tz),
                sub_calendars=[472104, 5298948],
                repeat_series_id=plenum_series_id,
                repeat_interval=1,
            )

        # One-day whole-day event, next Saturday.
        saturday = _weekday_on_or_after(today, 5, strictly_after=True)
        self.add_event(
            title="Kiezfest",
            starts_at=_local(saturday, time(0, 0), tz),
            ends_at=_local(saturday + timedelta(days=1), time(0, 0), tz),
            sub_calendars=[5298948],
            whole_day=True,
        )

        # Two-day whole-day event, in three weeks.
        start = today + timedelta(weeks=3)
        self.add_event(
            title="Soli-Wochenende",
            starts_at=_local(start, time(0, 0), tz),
            ends_at=_local(start + timedelta(days=2), time(0, 0), tz),
            sub_calendars=[472104, 5298948],
            whole_day=True,
        )

        # One-off, on the date the Instagram mock's seeded caption names
        # (mocks/dates.py keeps the two in step), so the link-suggestion
        # heuristic finds an exact caption-date match.
        day_12 = siebdruck_day(today)
        self.add_event(
            title="Siebdruck-Nachmittag",
            starts_at=_local(day_12, time(14, 0), tz),
            ends_at=_local(day_12, time(18, 0), tz),
            sub_calendars=[472104],
        )

        # Crosses midnight: a late show, not whole-day.
        show_day = today + timedelta(days=10)
        self.add_event(
            title="Kino-Nacht",
            starts_at=_local(show_day, time(22, 0), tz),
            ends_at=_local(show_day + timedelta(days=1), time(1, 0), tz),
            sub_calendars=[5298948],
        )

    def add_event(
        self,
        *,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        sub_calendars: list[int],
        whole_day: bool = False,
        repeat_series_id: int | None = None,
        repeat_interval: int = 0,
        text: str = "",
        who: str = "",
        where: str = "",
    ) -> Event:
        event_id = self.next_id
        self.next_id += 1
        event = Event(
            id=event_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            text=text,
            who=who,
            where=where,
            sub_calendars=sub_calendars,
            whole_day=whole_day,
            repeat_series_id=repeat_series_id,
            repeat_interval=repeat_interval,
        )
        self.events[event_id] = event
        return event

    def as_state_dict(self) -> dict:
        return {
            "calendar_id": CALENDAR_ID,
            "event_count": len(self.events),
            "events": sorted(e.title for e in self.events.values()),
        }


def _format_event(event: Event, tz: ZoneInfo, *, id_as_str: bool = False) -> dict:
    """The real API's own inconsistency, matched here: a listed event's `id` is a
    string (see the recorded EVENTS fixture in tests/calendar/test_kalender_digital.py),
    but a single event just created/fetched by id comes back with an int `id` (see that
    same file's `test_create_event_posts_the_expected_body_and_parses_the_follow_up_get`).
    KalenderDigitalClient._parse_events does `str(raw_id)` either way, so this is cosmetic
    fidelity only — it doesn't change what the adapter parses.
    """
    start_local = event.starts_at.astimezone(tz)
    end_local = event.ends_at.astimezone(tz)
    return {
        "id": str(event.id) if id_as_str else event.id,
        "start_date": start_local.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end_local.strftime("%Y-%m-%d %H:%M:%S"),
        "title": event.title,
        "text": event.text,
        "who": event.who,
        "where": event.where,
        "subCalendars": event.sub_calendars,
        "wholeDay": event.whole_day,
        "repeatSeriesId": event.repeat_series_id,
        "repeatInterval": event.repeat_interval,
        "imported": event.imported,
        "hasReminder": event.has_reminder,
        "hasRegistration": event.has_registration,
    }


def _parse_local(text: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=tz).astimezone(UTC)


def build_router(state: State | None = None) -> tuple[APIRouter, State]:
    if state is None:
        state = State(token=os.environ.get(TOKEN_ENV, DEFAULT_TOKEN))
        state.seed()

    router = APIRouter(prefix="/kalender")

    @router.get("/calendar")
    async def get_calendar(capabilityId: str = ""):
        if capabilityId != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        return {
            "id": CALENDAR_ID,
            "capabilityId": state.token,
            "title": "Viktoriastraße 18 (Mock)",
            "timeZone": TIME_ZONE,
            "subCalendars": [dict(sc, write=True) for sc in SUB_CALENDARS],
            "ics": f"https://export.kalender.digital/ics/mock/{state.token}/mock.ics",
            "userRole": "owner",
            "accountStatus": 0,
        }

    @router.get("/event")
    async def list_events(
        capabilityId: str = "", startDate: str = "", endDate: str = "", timeZone: str = TIME_ZONE
    ):
        if capabilityId != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        tz = ZoneInfo(timeZone)
        window_start = datetime.fromisoformat(startDate).replace(tzinfo=tz) if startDate else None
        window_end = (
            datetime.fromisoformat(endDate).replace(tzinfo=tz) + timedelta(days=1)
            if endDate
            else None
        )
        events = []
        for event in state.events.values():
            if window_start is not None and event.ends_at <= window_start.astimezone(UTC):
                continue
            if window_end is not None and event.starts_at >= window_end.astimezone(UTC):
                continue
            events.append(_format_event(event, tz, id_as_str=True))
        return events

    @router.post("/event")
    async def create_event(request: Request, timeZone: str = TIME_ZONE):
        body = await request.json()
        if body.get("capabilityId") != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        tz = ZoneInfo(timeZone)
        raw = body.get("event") or {}
        whole_day = bool(raw.get("wholeDay"))
        starts_at = _parse_local(raw["start_date"], tz)
        end_text = raw["end_date"]
        if whole_day and end_text.endswith("23:59:59"):
            # Real kalender.digital normalises a whole-day 23:59:59 end to
            # the following local midnight (the exclusive-end convention
            # every read already uses) — match that here too.
            last_day = datetime.fromisoformat(end_text).date()
            ends_at = _local(last_day + timedelta(days=1), time(0, 0), tz)
        else:
            ends_at = _parse_local(end_text, tz)

        event = state.add_event(
            title=raw.get("title") or "",
            starts_at=starts_at,
            ends_at=ends_at,
            sub_calendars=[int(x) for x in raw.get("subCalendars") or []],
            whole_day=whole_day,
            repeat_interval=int(raw.get("repeatInterval") or 0),
            text=raw.get("text") or "",
            who=raw.get("who") or "",
            where=raw.get("where") or "",
        )
        return {"eventId": event.id, "tempEventToken": "mock"}

    @router.get("/event/{event_id}")
    async def get_event(event_id: int, capabilityId: str = "", timeZone: str = TIME_ZONE):
        if capabilityId != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        event = state.events.get(event_id)
        if event is None:
            return JSONResponse({"msg": "NOT_FOUND"}, status_code=404)
        return _format_event(event, ZoneInfo(timeZone))

    @router.put("/event/{event_id}")
    async def update_event(event_id: int, request: Request, timeZone: str = TIME_ZONE):
        """Not called by KalenderDigitalClient today; kept for completeness."""
        body = await request.json()
        if body.get("capabilityId") != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        event = state.events.get(event_id)
        if event is None:
            return JSONResponse({"msg": "NOT_FOUND"}, status_code=404)
        tz = ZoneInfo(timeZone)
        raw = body.get("event") or {}
        if "start_date" in raw:
            event.starts_at = _parse_local(raw["start_date"], tz)
        if "end_date" in raw:
            event.ends_at = _parse_local(raw["end_date"], tz)
        if "title" in raw:
            event.title = raw["title"] or ""
        return _format_event(event, tz)

    @router.delete("/event/{event_id}")
    async def delete_event(event_id: int, capabilityId: str = ""):
        """Not called by KalenderDigitalClient today; kept for completeness."""
        if capabilityId != state.token:
            return JSONResponse(NO_ACCESS, status_code=403)
        state.events.pop(event_id, None)
        return {"ok": True}

    return router, state


def create_app(state: State | None = None) -> FastAPI:
    router, built_state = build_router(state)
    app = FastAPI(title="kalender.digital mock", docs_url=None, redoc_url=None)
    app.include_router(router)
    app.state.mock = built_state
    return app
