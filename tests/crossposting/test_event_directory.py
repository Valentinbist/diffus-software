"""CalendarEventDirectory: EventDirectory over the calendar context's own read use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from diffus.calendar.application.compose_post import GetComposeHint
from diffus.calendar.application.create_event import CreateEventForPost
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import (
    CalendarEvent,
    CalendarSnapshot,
    EventLink,
    LinkablePost,
    SubCalendar,
)
from diffus.calendar.domain.errors import CalendarError
from diffus.crossposting.domain.entities import NewEventRequest, SubCalendarOption
from diffus.crossposting.domain.errors import EventCreationError
from diffus.crossposting.infrastructure.calendar import CalendarEventDirectory
from tests.calendar.fakes import (
    FailingCalendar,
    FakeCalendar,
    FakeCalendarUnitOfWork,
    FakeEventLinks,
    FakeEvents,
    FakePostCatalog,
    FakeSubCalendars,
)

TZ = ZoneInfo("Europe/Berlin")
EMPTY_SNAPSHOT = CalendarSnapshot(sub_calendars=(), events=())


def make_event(
    event_id: str, title: str = "Plenum", removed_at: datetime | None = None
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
        removed_at=removed_at,
    )


def make_post(post_id: str = "p1") -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=None,
        permalink="",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=False,
    )


def make_directory_over(
    uow: FakeCalendarUnitOfWork,
    posts: list[LinkablePost] | None = None,
    calendar: FakeCalendar | FailingCalendar | None = None,
) -> CalendarEventDirectory:
    catalog = FakePostCatalog(posts or [])
    return CalendarEventDirectory(
        linked=GetLinkedEvents(uow=uow),
        hint=GetComposeHint(uow=uow, tz=TZ),
        link_post=LinkEventPost(uow=uow, posts=catalog),
        create_event_uc=CreateEventForPost(
            uow=uow, posts=catalog, calendar=calendar or FakeCalendar(EMPTY_SNAPSHOT), tz=TZ
        ),
    )


async def make_directory(
    events: list[CalendarEvent], links: list[EventLink]
) -> CalendarEventDirectory:
    uow = FakeCalendarUnitOfWork(events=FakeEvents(events), event_links=FakeEventLinks())
    for link in links:
        await uow.event_links.add(link.event_id, link.post_id)
    await uow.commit()
    return make_directory_over(uow)


def make_request(
    title: str = "Plenum",
    day: date = date(2026, 9, 10),
    start: time = time(18, 0),
    end: time = time(20, 0),
    whole_day: bool = False,
    description: str = "",
    location: str = "",
    who: str = "",
    sub_calendar_ids: frozenset[int] = frozenset(),
) -> NewEventRequest:
    return NewEventRequest(
        title=title,
        day=day,
        start=start,
        end=end,
        whole_day=whole_day,
        description=description,
        location=location,
        who=who,
        sub_calendar_ids=sub_calendar_ids,
    )


# -- for_posts (unchanged read side) ------------------------------------------


async def test_for_posts_maps_calendar_events_to_the_connectors_own_linked_event():
    event = make_event("e1", title="Widersetzen Plenum")
    directory = await make_directory([event], [EventLink(event.id, "p1", datetime.now(UTC))])

    found = await directory.for_posts(["p1", "p2"])

    assert set(found) == {"p1"}
    linked = found["p1"][0]
    assert linked.id == "e1"
    assert linked.title == "Widersetzen Plenum"
    assert linked.detail_url == "/calendar/events/e1"
    assert linked.removed is False


async def test_for_posts_marks_a_removed_event_but_still_returns_it():
    event = make_event("e1", removed_at=datetime.now(UTC))
    directory = await make_directory([event], [EventLink(event.id, "p1", datetime.now(UTC))])

    found = await directory.for_posts(["p1"])

    assert found["p1"][0].removed is True


# -- compose_hint ---------------------------------------------------------------


async def test_compose_hint_maps_the_calendars_own_hint_to_crosspostings_entity():
    event = make_event("e1", title="Plenum")
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    directory = make_directory_over(uow)

    hint = await directory.compose_hint("e1")

    assert hint is not None
    assert hint.event_id == "e1"
    assert hint.title == "Plenum"
    assert hint.detail_url == "/calendar/events/e1"
    assert "Plenum" in hint.caption


async def test_compose_hint_returns_none_for_an_unknown_event():
    directory = make_directory_over(FakeCalendarUnitOfWork())

    assert await directory.compose_hint("nope") is None


# -- link -------------------------------------------------------------------------


async def test_link_records_the_event_post_link_via_link_event_post():
    event = make_event("e1")
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    directory = make_directory_over(uow, posts=[make_post("p1")])

    await directory.link("e1", "p1")

    found = await GetLinkedEvents(uow=uow).for_posts(["p1"])
    assert found["p1"][0].id == "e1"


# -- event_form -------------------------------------------------------------------


async def test_event_form_without_a_post_prefills_today_and_lists_the_sub_calendars():
    sub_calendar = SubCalendar(id=1, name="Öffentliche Veranstaltung", color="#31859B", position=0)
    uow = FakeCalendarUnitOfWork(sub_calendars=FakeSubCalendars([sub_calendar]))
    directory = make_directory_over(uow)

    options = await directory.event_form(None)

    assert options is not None
    assert options.post_id is None
    assert options.sub_calendars == (
        SubCalendarOption(id=1, name="Öffentliche Veranstaltung", color="#31859B"),
    )
    assert options.prefill.title == ""


async def test_event_form_with_a_known_post_prefills_from_it_and_carries_its_id():
    post = make_post("p1")
    directory = make_directory_over(FakeCalendarUnitOfWork(), posts=[post])

    options = await directory.event_form("p1")

    assert options is not None
    assert options.post_id == "p1"


async def test_event_form_with_an_unknown_post_returns_none():
    directory = make_directory_over(FakeCalendarUnitOfWork(), posts=[])

    assert await directory.event_form("nope") is None


# -- create_event -------------------------------------------------------------------


async def test_create_event_maps_the_request_writes_the_event_and_links_the_post():
    post = make_post("p1")
    calendar = FakeCalendar(EMPTY_SNAPSHOT)
    uow = FakeCalendarUnitOfWork()
    directory = make_directory_over(uow, posts=[post], calendar=calendar)

    linked = await directory.create_event(make_request(), "p1")

    assert linked.id == "new-1"
    assert linked.title == "Plenum"
    assert linked.detail_url == "/calendar/events/new-1"
    found = await GetLinkedEvents(uow=uow).for_posts(["p1"])
    assert found["p1"][0].id == "new-1"


async def test_create_event_without_a_post_does_not_link_anything():
    calendar = FakeCalendar(EMPTY_SNAPSHOT)

    linked = await make_directory_over(FakeCalendarUnitOfWork(), calendar=calendar).create_event(
        make_request(), None
    )

    assert linked.id == "new-1"
    assert calendar.created[0].title == "Plenum"


async def test_create_event_wraps_a_validation_error_from_create_event_for_post():
    directory = make_directory_over(FakeCalendarUnitOfWork())

    with pytest.raises(EventCreationError):
        await directory.create_event(make_request(start=time(20, 0), end=time(18, 0)), None)


async def test_create_event_wraps_an_unknown_post_error():
    directory = make_directory_over(FakeCalendarUnitOfWork(), posts=[])

    with pytest.raises(EventCreationError):
        await directory.create_event(make_request(), "unknown-post")


async def test_create_event_wraps_a_calendar_gateway_error():
    failing = FailingCalendar(CalendarError("kalender.digital ist nicht erreichbar."))
    directory = make_directory_over(FakeCalendarUnitOfWork(), calendar=failing)

    with pytest.raises(EventCreationError, match="kalender.digital ist nicht erreichbar."):
        await directory.create_event(make_request(), None)
