"""CalendarEventDirectory: EventDirectory over the calendar context's own read use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from diffus.calendar.application.compose_post import GetComposeHint
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.domain.entities import CalendarEvent, EventLink, LinkablePost
from diffus.crossposting.infrastructure.calendar import CalendarEventDirectory
from tests.calendar.fakes import FakeCalendarUnitOfWork, FakeEventLinks, FakeEvents, FakePostCatalog

TZ = ZoneInfo("Europe/Berlin")


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
    uow: FakeCalendarUnitOfWork, posts: list[LinkablePost] | None = None
) -> CalendarEventDirectory:
    return CalendarEventDirectory(
        linked=GetLinkedEvents(uow=uow),
        hint=GetComposeHint(uow=uow, tz=TZ),
        link_post=LinkEventPost(uow=uow, posts=FakePostCatalog(posts or [])),
    )


async def make_directory(
    events: list[CalendarEvent], links: list[EventLink]
) -> CalendarEventDirectory:
    uow = FakeCalendarUnitOfWork(events=FakeEvents(events), event_links=FakeEventLinks())
    for link in links:
        await uow.event_links.add(link.event_id, link.post_id)
    await uow.commit()
    return make_directory_over(uow)


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
