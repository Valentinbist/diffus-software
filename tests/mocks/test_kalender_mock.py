"""Runs the real KalenderDigitalClient against mocks/kalender.py, over ASGITransport."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from diffus.calendar.domain.entities import NewEvent
from diffus.calendar.domain.errors import CalendarError
from diffus.calendar.infrastructure.kalender_digital import KalenderDigitalClient
from mocks.kalender import State, create_app

TOKEN = "mock-token"


@pytest.fixture
def state() -> State:
    s = State(token=TOKEN)
    s.seed()
    return s


@pytest.fixture
async def http(state: State):
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as client:
        yield client


def make_client(http: httpx.AsyncClient, token: str = TOKEN) -> KalenderDigitalClient:
    return KalenderDigitalClient(http, token=token, api_base="http://mock/kalender")


def wide_window() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=120), today + timedelta(days=200)


# -- fetch(): sub-calendars and events ----------------------------------------


async def test_fetch_returns_the_seven_sub_calendars(http: httpx.AsyncClient):
    client = make_client(http)
    start, end = wide_window()

    snapshot = await client.fetch(start, end)

    assert len(snapshot.sub_calendars) == 7


async def test_fetch_returns_every_seeded_event_within_a_wide_window(http: httpx.AsyncClient):
    client = make_client(http)
    start, end = wide_window()

    snapshot = await client.fetch(start, end)

    titles = {e.title for e in snapshot.events}
    assert titles == {
        "Stammtisch",
        "Plenum",
        "Kiezfest",
        "Soli-Wochenende",
        "Siebdruck-Nachmittag",
        "Kino-Nacht",
    }


async def test_stammtisch_occurrences_share_one_series_id(http: httpx.AsyncClient):
    client = make_client(http)
    start, end = wide_window()

    snapshot = await client.fetch(start, end)

    stammtisch = [e for e in snapshot.events if e.title == "Stammtisch"]
    assert len(stammtisch) == 21  # -8..+12 weeks, inclusive
    series_ids = {e.series_id for e in stammtisch}
    assert len(series_ids) == 1
    assert None not in series_ids


async def test_the_two_day_whole_day_event_spans_two_local_days(http: httpx.AsyncClient):
    client = make_client(http)
    start, end = wide_window()

    snapshot = await client.fetch(start, end)

    soli = next(e for e in snapshot.events if e.title == "Soli-Wochenende")
    assert soli.whole_day
    assert len(soli.local_days(ZoneInfo("Europe/Berlin"))) == 2


async def test_a_narrow_window_excludes_events_outside_it(http: httpx.AsyncClient):
    client = make_client(http)
    today = date.today()

    snapshot = await client.fetch(today, today)

    # Whatever's on today may or may not include a Stammtisch/Plenum
    # occurrence, but it must never include something three weeks out.
    assert not any(e.title == "Soli-Wochenende" for e in snapshot.events)


# -- create_event(): timed and whole-day, then a subsequent fetch sees it ----


def make_new_event(whole_day: bool = False) -> NewEvent:
    if whole_day:
        starts_at = datetime(2026, 9, 12, 22, 0, tzinfo=UTC)  # local midnight, 13. Sept CEST
        ends_at = datetime(2026, 9, 14, 22, 0, tzinfo=UTC)  # local midnight, 15. Sept (exclusive)
    else:
        starts_at = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)  # 18:00 CEST
        ends_at = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)  # 22:00 CEST
    return NewEvent(
        title="Fest",
        description="Text",
        who="Jona",
        location="Ort",
        starts_at=starts_at,
        ends_at=ends_at,
        whole_day=whole_day,
        sub_calendar_ids=frozenset({472104}),
    )


async def test_create_event_timed_comes_back_parsed(http: httpx.AsyncClient):
    client = make_client(http)

    created = await client.create_event(make_new_event())

    assert created.title == "Fest"
    assert created.who == "Jona"
    assert created.location == "Ort"
    assert not created.whole_day
    assert created.starts_at == datetime(2026, 9, 12, 16, 0, tzinfo=UTC)


async def test_create_event_whole_day_comes_back_with_the_exclusive_midnight_end(
    http: httpx.AsyncClient,
):
    client = make_client(http)

    created = await client.create_event(make_new_event(whole_day=True))

    assert created.whole_day
    assert created.ends_at == datetime(2026, 9, 14, 22, 0, tzinfo=UTC)


async def test_a_created_event_shows_up_in_a_later_fetch(http: httpx.AsyncClient):
    client = make_client(http)
    created = await client.create_event(make_new_event())

    snapshot = await client.fetch(date(2026, 9, 1), date(2026, 9, 30))

    assert any(e.id == created.id for e in snapshot.events)


# -- wrong token ---------------------------------------------------------------


async def test_create_event_with_a_wrong_token_raises_calendar_error(http: httpx.AsyncClient):
    client = make_client(http, token="wrong-token")

    with pytest.raises(CalendarError):
        await client.create_event(make_new_event())
