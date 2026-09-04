"""Unit tests for the caption template and compose hint the crossposting wizard prefills with."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from diffus.calendar.application.compose_post import GetComposeHint, caption_for_event
from diffus.calendar.domain.entities import CalendarEvent, SubCalendar
from tests.calendar.fakes import FakeCalendarUnitOfWork, FakeEvents

TZ = ZoneInfo("Europe/Berlin")

HAUPT_RAUM = SubCalendar(id=1, name="Haupt-Raum", color="#31859B", position=0)
GARTEN = SubCalendar(id=2, name="Garten", color="#9BBB59", position=1)


def make_event(
    title: str = "Fest",
    description: str | None = None,
    location: str | None = None,
    starts_at: datetime = datetime(2026, 9, 3, 16, 0, tzinfo=UTC),  # 18:00 CEST, Donnerstag
    ends_at: datetime = datetime(2026, 9, 3, 18, 0, tzinfo=UTC),  # 20:00 CEST
    whole_day: bool = False,
    sub_calendar_ids: frozenset[int] = frozenset(),
) -> CalendarEvent:
    return CalendarEvent(
        id="e1",
        title=title,
        description=description,
        who=None,
        location=location,
        starts_at=starts_at,
        ends_at=ends_at,
        whole_day=whole_day,
        sub_calendar_ids=sub_calendar_ids,
        series_id=None,
    )


# -- caption_for_event -------------------------------------------------------


def test_caption_for_a_timed_single_day_event_with_two_rooms_and_a_description():
    event = make_event(
        title="Sommerfest",
        description="Bringt gute Laune mit!",
        sub_calendar_ids=frozenset({1, 2}),
    )

    caption = caption_for_event(event, [HAUPT_RAUM, GARTEN], TZ)

    assert caption == (
        "Sommerfest\n"
        "📅 Donnerstag, 3. September · 18:00–20:00 Uhr\n"
        "📍 Viktoriastraße 18, Haupt-Raum, Garten\n\n"
        "Bringt gute Laune mit!"
    )


def test_caption_for_a_single_day_whole_day_event_omits_the_time():
    event = make_event(
        title="Ruhetag",
        starts_at=datetime(2026, 9, 3, 22, 0, tzinfo=UTC),  # local midnight, 4. September
        ends_at=datetime(2026, 9, 4, 22, 0, tzinfo=UTC),  # next local midnight
        whole_day=True,
    )

    caption = caption_for_event(event, [], TZ)

    assert caption == "Ruhetag\n📅 Freitag, 4. September\n📍 Viktoriastraße 18"


def test_caption_for_a_multi_day_whole_day_event_shows_the_first_and_last_day():
    event = make_event(
        title="Sommerlager",
        starts_at=datetime(2026, 8, 27, 22, 0, tzinfo=UTC),  # local midnight, 28. August
        ends_at=datetime(2026, 8, 30, 22, 0, tzinfo=UTC),  # local midnight, 31. August
        whole_day=True,
    )

    caption = caption_for_event(event, [], TZ)

    assert caption == (
        "Sommerlager\n📅 Freitag, 28. August – Sonntag, 30. August\n📍 Viktoriastraße 18"
    )


def test_caption_for_a_timed_event_crossing_midnight_shows_both_days():
    event = make_event(
        title="Saba bday celebration+clean up",
        starts_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),  # 16:00 CEST, Samstag
        ends_at=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),  # 15:00 CEST, Sonntag
    )

    caption = caption_for_event(event, [], TZ)

    assert caption == (
        "Saba bday celebration+clean up\n"
        "📅 Samstag, 10. Oktober · 16:00 – Sonntag, 11. Oktober, 15:00 Uhr\n"
        "📍 Viktoriastraße 18"
    )


def test_caption_uses_ohne_titel_for_an_untitled_event():
    event = make_event(title="")

    caption = caption_for_event(event, [], TZ)

    assert caption.startswith("Ohne Titel\n")


def test_caption_uses_the_events_own_location_instead_of_the_default():
    event = make_event(location="Café Botanika", sub_calendar_ids=frozenset({1}))

    caption = caption_for_event(event, [HAUPT_RAUM], TZ)

    assert "📍 Café Botanika, Haupt-Raum" in caption


# -- GetComposeHint -------------------------------------------------------------


async def test_compose_hint_returns_the_title_caption_and_detail_url():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event(title="Fest")]))

    hint = await GetComposeHint(uow=uow, tz=TZ).run("e1")

    assert hint is not None
    assert hint.event_id == "e1"
    assert hint.title == "Fest"
    assert hint.caption.startswith("Fest\n")
    assert hint.detail_url == "/calendar/events/e1"


async def test_compose_hint_returns_none_for_an_unknown_event():
    hint = await GetComposeHint(uow=FakeCalendarUnitOfWork(), tz=TZ).run("nope")

    assert hint is None


async def test_compose_hint_still_returns_a_hint_for_a_removed_event():
    removed = dataclasses.replace(make_event(title="Fest"), removed_at=datetime.now(UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([removed]))

    hint = await GetComposeHint(uow=uow, tz=TZ).run("e1")

    assert hint is not None
    assert hint.title == "Fest"


async def test_compose_hint_uses_ohne_titel_for_an_untitled_event():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event(title="")]))

    hint = await GetComposeHint(uow=uow, tz=TZ).run("e1")

    assert hint is not None
    assert hint.title == "Ohne Titel"
