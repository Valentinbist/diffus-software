"""Unit tests for the event → post compose wizard's use case, on fakes."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from diffus.calendar.application.compose_post import ComposePostForEvent, caption_for_event
from diffus.calendar.domain.entities import (
    CalendarEvent,
    InstagramState,
    PublishOptions,
    SubCalendar,
    TelegramTarget,
)
from diffus.calendar.domain.errors import PublishError, UnknownEventError
from tests.calendar.fakes import (
    FakeCalendarUnitOfWork,
    FakeEvents,
    FakePostCatalog,
    FakePublisher,
)

TZ = ZoneInfo("Europe/Berlin")

OPTIONS = PublishOptions(
    instagram=InstagramState.READY, targets=(TelegramTarget(address="c1", label="Telegram"),)
)

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


# -- ComposePostForEvent ------------------------------------------------------


def make_compose(
    uow: FakeCalendarUnitOfWork, publisher: FakePublisher | None = None
) -> ComposePostForEvent:
    return ComposePostForEvent(
        uow=uow,
        publisher=publisher if publisher is not None else FakePublisher(options=OPTIONS),
        posts=FakePostCatalog([]),
        tz=TZ,
    )


async def test_prefill_returns_the_view_prefilled_caption_and_publish_options():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    compose = make_compose(uow)

    form = await compose.prefill("e1")

    assert form is not None
    assert form.view.event.id == "e1"
    assert form.prefill.caption.startswith("Fest\n")
    assert form.options == OPTIONS


async def test_prefill_returns_none_for_an_unknown_event():
    compose = make_compose(FakeCalendarUnitOfWork())

    assert await compose.prefill("nope") is None


async def test_start_creates_a_draft_via_the_publisher_and_returns_its_id():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    publisher = FakePublisher(options=OPTIONS)
    compose = make_compose(uow, publisher)

    draft_id = await compose.start("e1", "Hallo", [("a.png", b"data")])

    assert draft_id == "d1"
    assert publisher.created == [("Hallo", ["a.png"])]


async def test_start_raises_unknown_event_error_for_a_missing_event():
    compose = make_compose(FakeCalendarUnitOfWork())

    with pytest.raises(UnknownEventError):
        await compose.start("nope", "Hallo", [])


async def test_preview_returns_the_view_and_the_drafts_preview():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    compose = make_compose(uow)

    preview = await compose.preview("e1", "d1")

    assert preview is not None
    assert preview.view.event.id == "e1"
    assert preview.draft.id == "d1"
    assert preview.options == OPTIONS


async def test_preview_returns_none_for_an_unknown_draft():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    compose = make_compose(uow)

    assert await compose.preview("e1", "no-such-draft") is None


async def test_preview_returns_none_for_an_unknown_event():
    compose = make_compose(FakeCalendarUnitOfWork())

    assert await compose.preview("nope", "d1") is None


async def test_publish_links_the_published_post_to_the_event_and_commits_once():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    publisher = FakePublisher(options=OPTIONS)
    compose = make_compose(uow, publisher)

    published = await compose.publish("e1", "d1", True, ["c1"])

    assert published.id == "diffus:d1"
    assert publisher.published == [("d1", True, ["c1"])]
    assert uow.commits == 1
    links = await uow.event_links.for_events(["e1"])
    assert [link.post_id for link in links["e1"]] == ["diffus:d1"]


async def test_publish_error_propagates_without_linking_anything():
    uow = FakeCalendarUnitOfWork(events=FakeEvents([make_event()]))
    publisher = FakePublisher(options=OPTIONS, fail=PublishError("Instagram: boom"))
    compose = make_compose(uow, publisher)

    with pytest.raises(PublishError):
        await compose.publish("e1", "d1", False, [])

    assert uow.commits == 0
    links = await uow.event_links.for_events(["e1"])
    assert links == {}


async def test_discard_delegates_to_the_publisher():
    publisher = FakePublisher(options=OPTIONS)
    compose = make_compose(FakeCalendarUnitOfWork(), publisher)

    await compose.discard("d1")

    assert publisher.discarded == ["d1"]
