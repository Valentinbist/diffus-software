"""Unit tests for the post → event wizard's use case, on fakes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from diffus.calendar.application.create_event import CreateEventForPost, EventForm
from diffus.calendar.domain.entities import CalendarSnapshot, LinkablePost, SubCalendar
from diffus.calendar.domain.errors import UnknownPostError
from tests.calendar.fakes import (
    FakeCalendar,
    FakeCalendarUnitOfWork,
    FakePostCatalog,
    FakeSubCalendars,
)

TZ = ZoneInfo("Europe/Berlin")

OEFFENTLICHE = SubCalendar(
    id=5298948, name="Öffentliche Veranstaltung", color="#9BBB59", position=0
)


def make_post(
    post_id: str = "p1",
    caption: str | None = "Text",
    posted_at: datetime = datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
) -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=caption,
        permalink=f"https://instagram.com/p/{post_id}/",
        posted_at=posted_at,
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=False,
    )


def make_use_case(
    uow: FakeCalendarUnitOfWork | None = None,
    posts: list[LinkablePost] | None = None,
    calendar: FakeCalendar | None = None,
) -> tuple[CreateEventForPost, FakeCalendar]:
    calendar = calendar if calendar is not None else FakeCalendar(CalendarSnapshot((), ()))
    use_case = CreateEventForPost(
        uow=uow if uow is not None else FakeCalendarUnitOfWork(),
        posts=FakePostCatalog(posts if posts is not None else [make_post()]),
        calendar=calendar,
        tz=TZ,
    )
    return use_case, calendar


# -- prefill -------------------------------------------------------------------


async def test_prefill_uses_the_first_caption_date_mention_as_the_day():
    post = make_post(
        caption="Kommt vorbei am 12.9.! Mehr dazu bald.",
        posted_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    use_case, _calendar = make_use_case(posts=[post])

    result = await use_case.prefill("p1")

    assert result is not None
    _post, prefill, _sub_calendars = result
    assert prefill.day == date(2026, 9, 12)


async def test_prefill_falls_back_to_the_posted_day_without_a_caption_date_mention():
    post = make_post(caption="Kein Datum hier.", posted_at=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    use_case, _calendar = make_use_case(posts=[post])

    result = await use_case.prefill("p1")

    assert result is not None
    _post, prefill, _sub_calendars = result
    assert prefill.day == post.posted_at.astimezone(TZ).date()


async def test_prefill_title_is_the_first_caption_line_cut_to_60_characters():
    long_line = "x" * 80
    post = make_post(caption=f"{long_line}\nzweite Zeile")
    use_case, _calendar = make_use_case(posts=[post])

    result = await use_case.prefill("p1")

    assert result is not None
    _post, prefill, _sub_calendars = result
    assert prefill.title == long_line[:59] + "…"
    assert len(prefill.title) == 60


async def test_prefill_defaults_to_the_public_sub_calendar_when_it_exists():
    uow = FakeCalendarUnitOfWork(sub_calendars=FakeSubCalendars([OEFFENTLICHE]))
    use_case, _calendar = make_use_case(uow=uow)

    result = await use_case.prefill("p1")

    assert result is not None
    _post, prefill, sub_calendars = result
    assert prefill.sub_calendar_ids == frozenset({OEFFENTLICHE.id})
    assert sub_calendars == [OEFFENTLICHE]


async def test_prefill_defaults_are_empty_when_the_public_sub_calendar_is_unknown():
    use_case, _calendar = make_use_case(uow=FakeCalendarUnitOfWork())

    result = await use_case.prefill("p1")

    assert result is not None
    _post, prefill, _sub_calendars = result
    assert prefill.sub_calendar_ids == frozenset()


async def test_prefill_returns_none_for_an_unknown_post():
    use_case, _calendar = make_use_case(posts=[])

    assert await use_case.prefill("nope") is None


# -- create --------------------------------------------------------------------


def make_form(
    day: date = date(2026, 9, 12),
    start: time = time(18, 0),
    end: time = time(22, 0),
    whole_day: bool = False,
) -> EventForm:
    return EventForm(
        title="Fest",
        day=day,
        start=start,
        end=end,
        whole_day=whole_day,
        description="Text",
        location="Ort",
        who="Jona",
        sub_calendar_ids=frozenset({OEFFENTLICHE.id}),
    )


async def test_create_calls_the_gateway_upserts_and_links_the_event_with_one_commit():
    uow = FakeCalendarUnitOfWork()
    use_case, calendar = make_use_case(uow=uow)
    form = make_form()

    event = await use_case.create("p1", form)

    assert len(calendar.created) == 1
    draft = calendar.created[0]
    assert draft.title == "Fest"
    assert draft.description == "Text"
    assert draft.location == "Ort"
    assert draft.who == "Jona"
    assert draft.whole_day is False
    assert draft.sub_calendar_ids == frozenset({OEFFENTLICHE.id})
    assert draft.starts_at == datetime(2026, 9, 12, 16, 0, tzinfo=UTC)  # 18:00 CEST
    assert draft.ends_at == datetime(2026, 9, 12, 20, 0, tzinfo=UTC)  # 22:00 CEST

    assert event.id == "new-1"
    stored = await uow.events.get("new-1")
    assert stored is not None
    links = await uow.event_links.for_events(["new-1"])
    assert [link.post_id for link in links["new-1"]] == ["p1"]
    assert uow.commits == 1


async def test_create_whole_day_spans_local_midnight_to_the_next_local_midnight():
    use_case, calendar = make_use_case()
    form = make_form(whole_day=True)

    await use_case.create("p1", form)

    draft = calendar.created[0]
    assert draft.starts_at == datetime(2026, 9, 11, 22, 0, tzinfo=UTC)  # local midnight, 12. Sept
    assert draft.ends_at == datetime(2026, 9, 12, 22, 0, tzinfo=UTC)  # local midnight, 13. Sept


async def test_create_raises_unknown_post_error_for_a_missing_post():
    use_case, _calendar = make_use_case(posts=[])

    with pytest.raises(UnknownPostError):
        await use_case.create("nope", make_form())


async def test_create_raises_value_error_when_the_end_is_not_after_the_start():
    use_case, _calendar = make_use_case()
    form = make_form(start=time(20, 0), end=time(18, 0))

    with pytest.raises(ValueError, match="Ende"):
        await use_case.create("p1", form)
