from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from diffus.calendar.domain.entities import NewEvent
from diffus.calendar.domain.errors import CalendarError
from diffus.calendar.infrastructure.kalender_digital import KalenderDigitalClient

TZ = ZoneInfo("Europe/Berlin")
TOKEN = "03e3bc8e2be173ff9c8b"

CALENDAR = {
    "id": 48963,
    "capabilityId": "03e3bc8e2be173ff9c8b",
    "title": "Viktoriastraße 18 (diffus.space, FAU)",
    "timeZone": "Europe/Berlin",
    "subCalendars": [
        {
            "id": 472104,
            "color": "#31859B",
            "colorText": "#FFFFFF",
            "name": "Haupt-Raum",
            "write": True,
            "ics": (
                "https://export.kalender.digital/ics/472104/03e3bc8e2be173ff9c8b/"
                "haupt-raum.ics?past_months=3&future_months=36"
            ),
        },
        {
            "id": 5298948,
            "color": "#9BBB59",
            "colorText": "#FFFFFF",
            "name": "Öffentliche Veranstaltung",
            "write": True,
        },
        {"id": 5298949, "color": "not-a-colour", "name": "Do not disturb!"},
        {"color": "#FF0000", "name": "no id, must be skipped"},
    ],
}

EVENTS = [
    {
        "id": "3571355485",
        "start_date": "2026-08-03 18:00:00",
        "end_date": "2026-08-03 22:00:00",
        "title": "Widersetzen Plenum",
        "text": "",
        "who": "",
        "where": "",
        "subCalendars": [472104, 5298948],
        "wholeDay": False,
        "repeatSeriesId": None,
        "repeatInterval": 0,
        "imported": False,
        "hasReminder": False,
        "hasRegistration": False,
    },
    {
        "id": "1756742242",
        "start_date": "2026-08-04 18:30:00",
        "end_date": "2026-08-04 21:00:00",
        "title": "Arbeitstreffen FAU",
        "text": "Bei Kollision oder Fragen Leyer oder Arne Fragen.",
        "who": "",
        "where": "",
        "subCalendars": [472104, 5298948],
        "wholeDay": False,
        "repeatSeriesId": 1756742227,
        "repeatInterval": 5,
        "imported": False,
        "hasReminder": False,
        "hasRegistration": False,
    },
    {
        "id": "3068541234",
        "start_date": "2026-08-08 00:00:00",
        "end_date": "2026-08-09 00:00:00",
        "title": "Jubiläum Tacheles",
        "text": "",
        "who": "Jona",
        "where": "",
        "subCalendars": [472104, 472114, 5298948, 6001525],
        "wholeDay": True,
        "repeatSeriesId": None,
        "repeatInterval": 0,
        "imported": False,
        "hasReminder": False,
        "hasRegistration": False,
    },
    {
        "id": "2257120274",
        "start_date": "2026-08-28 00:00:00",
        "end_date": "2026-08-30 00:00:00",
        "title": "CSD Aachen",
        "text": "",
        "who": "",
        "where": "",
        "subCalendars": [5298948],
        "wholeDay": True,
        "repeatSeriesId": None,
        "repeatInterval": 0,
        "imported": False,
        "hasReminder": False,
        "hasRegistration": False,
    },
    {
        "id": "3893376883",
        "start_date": "2026-10-10 16:00:00",
        "end_date": "2026-10-11 15:00:00",
        "title": "Saba bday celebration+clean up",
        "text": "The gathering is on 10.10 the day after is booked to clean up properly",
        "who": "Saba 015773625685",
        "where": "",
        "subCalendars": [472104, 472114, 5298949],
        "wholeDay": False,
        "repeatSeriesId": None,
        "repeatInterval": 0,
        "imported": False,
        "hasReminder": False,
        "hasRegistration": False,
    },
    {
        "id": "1756756741",
        "start_date": "2026-11-02 18:30:00",
        "end_date": "2026-11-02 21:00:00",
        "title": "Arbeitstreffen FAU",
        "text": "Bei Kollision oder Fragen Leyer oder Arne Fragen.",
        "who": "",
        "where": "",
        "subCalendars": [472104, 5298948],
        "wholeDay": False,
        "repeatSeriesId": 1756756720,
        "repeatInterval": 5,
    },
    {
        "start_date": "2026-11-03 10:00:00",
        "end_date": "2026-11-03 11:00:00",
        "title": "no id, must be skipped",
        "subCalendars": [],
    },
]


# -- _parse_sub_calendars -----------------------------------------------


def test_parse_sub_calendars_assigns_position_from_listed_order():
    sub_calendars = KalenderDigitalClient._parse_sub_calendars(CALENDAR)

    assert [sc.id for sc in sub_calendars] == [472104, 5298948, 5298949]
    assert [sc.position for sc in sub_calendars] == [0, 1, 2]


def test_parse_sub_calendars_keeps_a_valid_colour():
    sub_calendars = KalenderDigitalClient._parse_sub_calendars(CALENDAR)

    haupt_raum = next(sc for sc in sub_calendars if sc.id == 472104)
    assert haupt_raum.name == "Haupt-Raum"
    assert haupt_raum.color == "#31859B"


def test_parse_sub_calendars_falls_back_to_the_default_colour_when_malformed():
    sub_calendars = KalenderDigitalClient._parse_sub_calendars(CALENDAR)

    do_not_disturb = next(sc for sc in sub_calendars if sc.id == 5298949)
    assert do_not_disturb.color == "#4C4C4C"


def test_parse_sub_calendars_skips_entries_without_an_id():
    sub_calendars = KalenderDigitalClient._parse_sub_calendars(CALENDAR)

    assert all(sc.name != "no id, must be skipped" for sc in sub_calendars)


# -- _parse_events --------------------------------------------------------


def test_parse_events_converts_local_time_to_utc_in_summer():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    plenum = next(e for e in events if e.id == "3571355485")
    assert plenum.starts_at == datetime(2026, 8, 3, 16, 0, tzinfo=UTC)
    assert plenum.ends_at == datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def test_parse_events_converts_local_time_to_utc_after_the_dst_switch():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    arbeitstreffen = next(e for e in events if e.id == "1756756741")
    assert arbeitstreffen.starts_at == datetime(2026, 11, 2, 17, 30, tzinfo=UTC)
    assert arbeitstreffen.ends_at == datetime(2026, 11, 2, 20, 0, tzinfo=UTC)


def test_parse_events_ids_are_strings():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    assert all(isinstance(e.id, str) for e in events)


def test_parse_events_keeps_the_whole_day_flag_and_exclusive_end():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    jubilaeum = next(e for e in events if e.id == "3068541234")
    assert jubilaeum.whole_day is True
    assert jubilaeum.starts_at == datetime(2026, 8, 7, 22, 0, tzinfo=UTC)
    assert jubilaeum.ends_at == datetime(2026, 8, 8, 22, 0, tzinfo=UTC)
    assert jubilaeum.local_days(TZ) == [date(2026, 8, 8)]


def test_parse_events_two_day_whole_day_event_spans_two_local_days():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    csd = next(e for e in events if e.id == "2257120274")
    assert csd.local_days(TZ) == [date(2026, 8, 28), date(2026, 8, 29)]


def test_parse_events_timed_event_crossing_a_calendar_day_spans_two_local_days():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    saba = next(e for e in events if e.id == "3893376883")
    assert saba.local_days(TZ) == [date(2026, 10, 10), date(2026, 10, 11)]


def test_parse_events_sub_calendar_ids_are_a_frozenset_of_ints():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    plenum = next(e for e in events if e.id == "3571355485")
    assert plenum.sub_calendar_ids == frozenset({472104, 5298948})


def test_parse_events_keeps_the_repeat_series_id():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    arbeitstreffen = next(e for e in events if e.id == "1756742242")
    assert arbeitstreffen.series_id == 1756742227


def test_parse_events_empty_text_fields_become_none():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    plenum = next(e for e in events if e.id == "3571355485")
    assert plenum.description is None
    assert plenum.who is None
    assert plenum.location is None


def test_parse_events_keeps_a_non_empty_who():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    jubilaeum = next(e for e in events if e.id == "3068541234")
    assert jubilaeum.who == "Jona"


def test_parse_events_skips_items_without_an_id():
    events = KalenderDigitalClient._parse_events(EVENTS, TZ)

    assert all(e.title != "no id, must be skipped" for e in events)


# -- fetch() against a mocked transport -----------------------------------


def make_client(handler) -> KalenderDigitalClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return KalenderDigitalClient(http, token="03e3bc8e2be173ff9c8b")


async def test_fetch_sends_the_expected_query_params_to_both_endpoints():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/calendar":
            return httpx.Response(200, json=CALENDAR)
        return httpx.Response(200, json=EVENTS)

    client = make_client(handler)

    snapshot = await client.fetch(date(2026, 6, 1), date(2027, 3, 31))

    assert len(requests) == 2
    calendar_req, event_req = requests
    assert calendar_req.url.params["capabilityId"] == "03e3bc8e2be173ff9c8b"
    assert event_req.url.params["capabilityId"] == "03e3bc8e2be173ff9c8b"
    assert event_req.url.params["startDate"] == "2026-06-01"
    assert event_req.url.params["endDate"] == "2027-03-31"
    assert event_req.url.params["timeZone"] == "Europe/Berlin"
    assert len(snapshot.sub_calendars) == 3
    assert len(snapshot.events) == 6


async def test_fetch_raises_on_a_server_error_from_the_event_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/calendar":
            return httpx.Response(200, json=CALENDAR)
        return httpx.Response(500, text="boom")

    client = make_client(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await client.fetch(date(2026, 6, 1), date(2027, 3, 31))


# -- create_event() against a mocked transport -----------------------------


def make_new_event(
    starts_at: datetime = datetime(2026, 9, 12, 16, 0, tzinfo=UTC),  # 18:00 CEST
    ends_at: datetime = datetime(2026, 9, 12, 20, 0, tzinfo=UTC),  # 22:00 CEST
    whole_day: bool = False,
) -> NewEvent:
    return NewEvent(
        title="Fest",
        description="Text",
        who="Jona",
        location="Ort",
        starts_at=starts_at,
        ends_at=ends_at,
        whole_day=whole_day,
        sub_calendar_ids=frozenset({5298948, 472104}),
    )


async def test_create_event_posts_the_expected_body_and_parses_the_follow_up_get():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"eventId": 999})
        return httpx.Response(200, json=EVENTS[0] | {"id": 999})  # a dict, not a list

    client = make_client(handler)

    event = await client.create_event(make_new_event())

    assert len(requests) == 2
    post_req, get_req = requests
    body = json.loads(post_req.content)
    assert body == {
        "event": {
            "start_date": "2026-09-12 18:00:00",
            "end_date": "2026-09-12 22:00:00",
            "title": "Fest",
            "text": "Text",
            "who": "Jona",
            "where": "Ort",
            "subCalendars": [472104, 5298948],
            "wholeDay": False,
            "repeatInterval": 0,
        },
        "capabilityId": TOKEN,
        "seriesEdit": None,
    }
    assert post_req.url.params["timeZone"] == "Europe/Berlin"
    assert get_req.url.path == "/event/999"
    assert get_req.url.params["capabilityId"] == TOKEN
    assert event.id == "999"


async def test_create_event_whole_day_sends_the_last_days_23_59_59():
    posted: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(200, json={"eventId": 1000})
        return httpx.Response(200, json=EVENTS[0] | {"id": 1000})

    client = make_client(handler)
    draft = make_new_event(
        whole_day=True,
        starts_at=datetime(2026, 8, 27, 22, 0, tzinfo=UTC),  # local midnight, 28. August
        ends_at=datetime(2026, 8, 30, 22, 0, tzinfo=UTC),  # local midnight, 31. August (exclusive)
    )

    await client.create_event(draft)

    body = json.loads(posted[0].content)
    assert body["event"]["start_date"] == "2026-08-28 00:00:00"
    assert body["event"]["end_date"] == "2026-08-30 23:59:59"


async def test_create_event_raises_calendar_error_without_the_token_when_the_get_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"eventId": 999})
        return httpx.Response(500, text="boom")

    client = make_client(handler)

    with pytest.raises(CalendarError) as exc_info:
        await client.create_event(make_new_event())

    assert TOKEN not in str(exc_info.value)
