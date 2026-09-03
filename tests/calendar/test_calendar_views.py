"""GetCalendarEvents, GetEventDetail and LinkEventPost: the calendar's read side and linking."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from diffus.calendar.application.calendar_events import EventPostStatus, GetCalendarEvents
from diffus.calendar.application.event_detail import GetEventDetail
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost, SubCalendar
from diffus.calendar.domain.errors import UnknownEventError, UnknownPostError
from tests.calendar.fakes import (
    FakeCalendarUnitOfWork,
    FakeEventLinks,
    FakeEvents,
    FakePostCatalog,
    FakeSubCalendars,
)

TZ = ZoneInfo("Europe/Berlin")


def make_event(
    event_id: str,
    starts_at: datetime,
    title: str = "Test",
    sub_calendar_ids: frozenset[int] = frozenset(),
    removed_at: datetime | None = None,
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        whole_day=False,
        sub_calendar_ids=sub_calendar_ids,
        series_id=None,
        removed_at=removed_at,
    )


def make_post(
    post_id: str, posted_at: datetime, delivered: bool = False, caption: str | None = None
) -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=caption,
        permalink=f"https://instagram.com/p/{post_id}/",
        posted_at=posted_at,
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=delivered,
    )


# -- GetCalendarEvents -------------------------------------------------------


async def test_the_day_window_is_interpreted_in_the_given_timezone():
    # 2026-09-04 22:30 UTC is 2026-09-05 00:30 CEST: local day 09-05, just after local midnight.
    just_after_midnight = make_event("e1", datetime(2026, 9, 4, 22, 30, tzinfo=UTC))
    next_local_day = make_event("e2", datetime(2026, 9, 6, 10, 0, tzinfo=UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([just_after_midnight, next_local_day]))
    use_case = GetCalendarEvents(uow=uow, posts=FakePostCatalog([]), tz=TZ)

    page = await use_case.run(date(2026, 9, 5), date(2026, 9, 5))

    assert [v.event.id for v in page.events] == ["e1"]


async def test_filtering_by_sub_calendar_id():
    e1 = make_event("e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC), sub_calendar_ids=frozenset({1}))
    e2 = make_event("e2", datetime(2026, 9, 5, 11, 0, tzinfo=UTC), sub_calendar_ids=frozenset({2}))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([e1, e2]))
    use_case = GetCalendarEvents(uow=uow, posts=FakePostCatalog([]), tz=TZ)

    page = await use_case.run(date(2026, 9, 5), date(2026, 9, 5), sub_calendar_ids=[2])

    assert [v.event.id for v in page.events] == ["e2"]


async def test_post_status_reflects_linked_and_delivered_posts():
    e_none = make_event("none", datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    e_linked = make_event("linked", datetime(2026, 9, 5, 11, 0, tzinfo=UTC))
    e_delivered = make_event("delivered", datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    links = FakeEventLinks()
    await links.add("linked", "p-linked")
    await links.add("delivered", "p-delivered")
    links.dirty = False
    posts = FakePostCatalog(
        [
            make_post("p-linked", datetime(2026, 9, 1, tzinfo=UTC), delivered=False),
            make_post("p-delivered", datetime(2026, 9, 1, tzinfo=UTC), delivered=True),
        ]
    )
    events = FakeEvents([e_none, e_linked, e_delivered])
    uow = FakeCalendarUnitOfWork(events=events, event_links=links)
    use_case = GetCalendarEvents(uow=uow, posts=posts, tz=TZ)

    page = await use_case.run(date(2026, 9, 5), date(2026, 9, 5))

    status_by_id = {v.event.id: v.post_status for v in page.events}
    assert status_by_id["none"] == EventPostStatus.NONE
    assert status_by_id["linked"] == EventPostStatus.LINKED
    assert status_by_id["delivered"] == EventPostStatus.DELIVERED


async def test_event_sub_calendars_are_resolved_in_position_order():
    sc_a = SubCalendar(id=1, name="A", color="#111111", position=1)
    sc_b = SubCalendar(id=2, name="B", color="#222222", position=0)
    event = make_event(
        "e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC), sub_calendar_ids=frozenset({1, 2})
    )
    uow = FakeCalendarUnitOfWork(
        sub_calendars=FakeSubCalendars([sc_a, sc_b]), events=FakeEvents([event])
    )
    use_case = GetCalendarEvents(uow=uow, posts=FakePostCatalog([]), tz=TZ)

    page = await use_case.run(date(2026, 9, 5), date(2026, 9, 5))

    assert [sc.id for sc in page.events[0].sub_calendars] == [2, 1]


# -- GetEventDetail -----------------------------------------------------------


async def test_linked_posts_come_back_in_link_order_not_lookup_order():
    event = make_event("e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    links = FakeEventLinks()
    await links.add("e1", "p2")
    await links.add("e1", "p1")
    links.dirty = False
    posts = FakePostCatalog(
        [
            make_post("p1", datetime(2026, 9, 1, tzinfo=UTC)),
            make_post("p2", datetime(2026, 9, 2, tzinfo=UTC)),
        ]
    )
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]), event_links=links)
    use_case = GetEventDetail(uow=uow, posts=posts, tz=TZ)

    detail = await use_case.run("e1")

    assert detail is not None
    assert [p.id for p in detail.linked] == ["p2", "p1"]


async def test_suggestions_use_the_scoring_heuristic():
    event = make_event("e1", datetime(2026, 9, 5, 16, 0, tzinfo=UTC), title="Siebdruck")
    matching = make_post("p-match", datetime(2026, 9, 1, tzinfo=UTC), caption="Siebdruck Workshop")
    unrelated = make_post("p-other", datetime(2026, 1, 1, tzinfo=UTC), caption="Nichts davon")
    posts = FakePostCatalog([matching, unrelated])
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    use_case = GetEventDetail(uow=uow, posts=posts, tz=TZ)

    detail = await use_case.run("e1")

    assert detail is not None
    assert [s.post.id for s in detail.suggestions] == ["p-match"]
    assert detail.suggestions[0].reasons
    assert [p.id for p in detail.recent] == ["p-other"]


async def test_the_post_picker_never_shows_the_same_post_twice():
    event = make_event("e1", datetime(2026, 9, 5, 16, 0, tzinfo=UTC), title="Siebdruck")
    linked_post = make_post(
        "p-linked", datetime(2026, 9, 1, tzinfo=UTC), caption="Siebdruck Workshop"
    )
    suggested_post = make_post(
        "p-suggested", datetime(2026, 9, 2, tzinfo=UTC), caption="Siebdruck"
    )
    plain_post = make_post("p-plain", datetime(2026, 1, 1, tzinfo=UTC), caption="Nichts")
    posts = FakePostCatalog([linked_post, suggested_post, plain_post])
    links = FakeEventLinks()
    await links.add("e1", "p-linked")
    links.dirty = False
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]), event_links=links)
    use_case = GetEventDetail(uow=uow, posts=posts, tz=TZ)

    detail = await use_case.run("e1")

    assert detail is not None
    assert [p.id for p in detail.linked] == ["p-linked"]
    assert [s.post.id for s in detail.suggestions] == ["p-suggested"]
    assert [p.id for p in detail.recent] == ["p-plain"]


async def test_run_returns_none_for_an_unknown_event():
    uow = FakeCalendarUnitOfWork()
    use_case = GetEventDetail(uow=uow, posts=FakePostCatalog([]), tz=TZ)

    assert await use_case.run("nope") is None


async def test_run_still_works_for_a_removed_event():
    removed = make_event(
        "e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC), removed_at=datetime(2026, 9, 4, tzinfo=UTC)
    )
    uow = FakeCalendarUnitOfWork(events=FakeEvents([removed]))
    use_case = GetEventDetail(uow=uow, posts=FakePostCatalog([]), tz=TZ)

    detail = await use_case.run("e1")

    assert detail is not None
    assert detail.view.event.removed


# -- LinkEventPost ------------------------------------------------------------


async def test_add_raises_for_an_unknown_event():
    uow = FakeCalendarUnitOfWork()
    posts = FakePostCatalog([make_post("p1", datetime(2026, 9, 1, tzinfo=UTC))])
    use_case = LinkEventPost(uow=uow, posts=posts)

    with pytest.raises(UnknownEventError):
        await use_case.add("nope", "p1")


async def test_add_raises_for_an_unknown_post():
    event = make_event("e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    use_case = LinkEventPost(uow=uow, posts=FakePostCatalog([]))

    with pytest.raises(UnknownPostError):
        await use_case.add("e1", "nope")


async def test_add_links_the_post_and_commits_once():
    event = make_event("e1", datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    posts = FakePostCatalog([make_post("p1", datetime(2026, 9, 1, tzinfo=UTC))])
    use_case = LinkEventPost(uow=uow, posts=posts)

    await use_case.add("e1", "p1")

    assert uow.commits == 1
    linked = await uow.event_links.for_events(["e1"])
    assert [link.post_id for link in linked["e1"]] == ["p1"]


async def test_remove_is_idempotent_and_commits_every_time():
    uow = FakeCalendarUnitOfWork()
    use_case = LinkEventPost(uow=uow, posts=FakePostCatalog([]))

    await use_case.remove("e1", "p1")
    await use_case.remove("e1", "p1")

    assert uow.commits == 2
