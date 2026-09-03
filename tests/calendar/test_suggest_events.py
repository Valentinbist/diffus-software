"""suggest_events: scoring candidate events against a post for the link-from-post picker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.suggest_posts import SuggestionReason, suggest_events
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost

TZ = ZoneInfo("Europe/Berlin")

POST_POSTED_AT = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def make_post(caption: str | None, posted_at: datetime = POST_POSTED_AT) -> LinkablePost:
    return LinkablePost(
        id="p1",
        caption=caption,
        permalink="https://instagram.com/p/p1/",
        posted_at=posted_at,
        thumbnail_url=None,
        detail_url="/posts/p1",
        delivered=False,
    )


def make_event(event_id: str, title: str, starts_at: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
    )


def test_date_mention_outranks_title_overlap_which_outranks_recency():
    # Posted well outside the 14-day recency window, so only the date mention scores.
    post = make_post("📅 5. September", posted_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
    date_match = make_event("e-date", "Sonstiges", datetime(2026, 9, 5, 16, 0, tzinfo=UTC))
    title_match = make_event(
        "e-title", "Siebdruck-Workshop", datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
    )
    post_for_title = make_post("Siebdruck Workshop, kommt vorbei")

    date_suggestions = suggest_events(post, [date_match, title_match], TZ)
    assert date_suggestions[0].event_id == "e-date"
    assert date_suggestions[0].reasons == (SuggestionReason.DATE,)

    title_suggestions = suggest_events(post_for_title, [title_match], TZ)
    assert title_suggestions[0].event_id == "e-title"
    assert title_suggestions[0].reasons == (SuggestionReason.TITLE,)


def test_a_post_close_to_the_event_scores_as_recent():
    post = make_post("Schaut mal vorbei")
    event = make_event("e1", "Sonstiges", datetime(2026, 9, 5, 16, 0, tzinfo=UTC))

    suggestions = suggest_events(post, [event], TZ)

    assert [s.event_id for s in suggestions] == ["e1"]
    assert suggestions[0].reasons == (SuggestionReason.RECENT,)


def test_an_event_that_scores_zero_is_excluded():
    post = make_post("Nichts davon passt")
    event = make_event("e1", "Sonstiges", datetime(2027, 1, 1, tzinfo=UTC))

    assert suggest_events(post, [event], TZ) == []


def test_limit_caps_the_number_of_suggestions_returned():
    post = make_post("Schaut mal vorbei")
    events = [
        make_event(f"e{i}", "Sonstiges", datetime(2026, 9, 5, tzinfo=UTC) + timedelta(minutes=i))
        for i in range(6)
    ]

    suggestions = suggest_events(post, events, TZ, limit=3)

    assert len(suggestions) == 3


def test_tied_scores_are_ordered_by_earliest_start():
    post = make_post("Schaut mal vorbei")
    later = make_event("e-later", "Sonstiges", datetime(2026, 9, 10, tzinfo=UTC))
    earlier = make_event("e-earlier", "Sonstiges", datetime(2026, 9, 5, tzinfo=UTC))

    suggestions = suggest_events(post, [later, earlier], TZ)

    assert [s.event_id for s in suggestions] == ["e-earlier", "e-later"]
    assert suggestions[0].score == suggestions[1].score
