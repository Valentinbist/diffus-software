"""GetLinkPicker: the "link from a post" page's read side — suggestions plus the plain list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.link_picker import GetLinkPicker
from diffus.calendar.application.suggest_posts import SuggestionReason
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost, SubCalendar
from tests.calendar.fakes import (
    FakeCalendarUnitOfWork,
    FakeEventLinks,
    FakeEvents,
    FakePostCatalog,
    FakeSubCalendars,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

SUB_CALENDAR = SubCalendar(id=1, name="Öffentliche Veranstaltung", color="#9BBB59", position=0)


def make_post(post_id: str = "p1", caption: str | None = "Schaut mal vorbei") -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=caption,
        permalink=f"https://instagram.com/p/{post_id}/",
        posted_at=NOW - timedelta(days=1),
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=False,
    )


def make_event(event_id: str, starts_at: datetime, title: str = "Sonstiges") -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        whole_day=False,
        sub_calendar_ids=frozenset({SUB_CALENDAR.id}),
        series_id=None,
    )


async def test_run_returns_none_for_an_unknown_post():
    picker = GetLinkPicker(uow=FakeCalendarUnitOfWork(), posts=FakePostCatalog([]), tz=TZ)

    assert await picker.run("nope", NOW) is None


async def test_run_splits_suggested_events_from_the_plain_upcoming_list():
    close_event = make_event("e-close", NOW + timedelta(days=5))
    far_event = make_event("e-far", NOW + timedelta(days=40))
    uow = FakeCalendarUnitOfWork(
        sub_calendars=FakeSubCalendars([SUB_CALENDAR]),
        events=FakeEvents([close_event, far_event]),
    )
    posts = FakePostCatalog([make_post()])
    picker = GetLinkPicker(uow=uow, posts=posts, tz=TZ)

    result = await picker.run("p1", NOW)

    assert result is not None
    assert result.post.id == "p1"
    assert [e.event.id for e in result.suggestions] == ["e-close"]
    assert result.suggestions[0].reasons == (SuggestionReason.RECENT,)
    assert result.suggestions[0].sub_calendars == [SUB_CALENDAR]
    # The suggested event never also shows up in the plain list.
    assert [e.event.id for e in result.events] == ["e-far"]


async def test_run_flags_events_already_linked_to_the_post():
    event = make_event("e1", NOW + timedelta(days=90))  # outside the suggestion window
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]), event_links=FakeEventLinks())
    await uow.event_links.add(event.id, "p1")
    await uow.commit()
    picker = GetLinkPicker(uow=uow, posts=FakePostCatalog([make_post()]), tz=TZ, window_days=100)

    result = await picker.run("p1", NOW)

    assert result is not None
    assert result.events[0].linked is True


async def test_window_days_limits_which_events_are_considered():
    far_event = make_event("e-far", NOW + timedelta(days=90))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([far_event]))
    picker = GetLinkPicker(uow=uow, posts=FakePostCatalog([make_post()]), tz=TZ, window_days=60)

    result = await picker.run("p1", NOW)

    assert result is not None
    assert result.events == []
    assert result.suggestions == []
