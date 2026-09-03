"""suggest_posts: scoring candidate posts against an event for the link picker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.suggest_posts import SuggestionReason, suggest_posts
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost

TZ = ZoneInfo("Europe/Berlin")

EVENT_START = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)  # 18:00 CEST, local day 2026-09-05


def make_event(title: str = "Siebdruck-Workshop") -> CalendarEvent:
    return CalendarEvent(
        id="e1",
        title=title,
        description=None,
        who=None,
        location=None,
        starts_at=EVENT_START,
        ends_at=EVENT_START + timedelta(hours=2),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
    )


def make_post(post_id: str, caption: str | None, posted_at: datetime) -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=caption,
        permalink=f"https://instagram.com/p/{post_id}/",
        posted_at=posted_at,
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=False,
    )


def test_date_mention_outranks_title_overlap_which_outranks_recency():
    event = make_event()
    date_match = make_post(
        "p-date", "📅 5. September", posted_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    )
    title_match = make_post(
        "p-title",
        "Workshop Siebdruck, kommt vorbei",
        posted_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )
    recent_only = make_post(
        "p-recent", "Schaut mal vorbei", posted_at=datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    )

    suggestions = suggest_posts(event, [date_match, title_match, recent_only], TZ)

    assert [s.post_id for s in suggestions] == ["p-date", "p-title", "p-recent"]
    assert suggestions[0].score == 3
    assert suggestions[0].reasons == (SuggestionReason.DATE,)
    assert suggestions[1].score == 2
    assert suggestions[1].reasons == (SuggestionReason.TITLE,)
    assert suggestions[2].score == 1
    assert suggestions[2].reasons == (SuggestionReason.RECENT,)


def test_title_overlap_score_is_capped_at_two_even_with_three_shared_words():
    event = make_event(title="Siebdruck Workshop Ausstellung")
    post = make_post(
        "p1",
        "Siebdruck Workshop Ausstellung heute Abend",
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    suggestions = suggest_posts(event, [post], TZ)

    assert suggestions[0].score == 2
    assert suggestions[0].reasons == (SuggestionReason.TITLE,)


def test_stopwords_do_not_count_toward_the_title_score():
    event = make_event(title="Raum ist offen für alle")
    post = make_post(
        "p1",
        "Der Raum ist heute offen für alle willkommen",
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert suggest_posts(event, [post], TZ) == []


def test_a_post_that_scores_zero_is_excluded_even_when_others_qualify():
    event = make_event()
    unrelated = make_post(
        "p-unrelated", "Nichts davon passt", posted_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    qualifying = make_post(
        "p-recent", "Schaut mal vorbei", posted_at=datetime(2026, 8, 30, tzinfo=UTC)
    )

    suggestions = suggest_posts(event, [unrelated, qualifying], TZ)

    assert [s.post_id for s in suggestions] == ["p-recent"]


def test_limit_caps_the_number_of_suggestions_returned():
    event = make_event()
    base = datetime(2026, 8, 30, tzinfo=UTC)
    posts = [
        make_post(f"p{i}", "Schaut mal vorbei", posted_at=base + timedelta(minutes=i))
        for i in range(6)
    ]

    suggestions = suggest_posts(event, posts, TZ, limit=3)

    assert len(suggestions) == 3


def test_tied_scores_are_ordered_newest_post_first():
    event = make_event()
    older = make_post("p-older", "Schaut mal vorbei", posted_at=datetime(2026, 8, 25, tzinfo=UTC))
    newer = make_post("p-newer", "Schaut mal vorbei", posted_at=datetime(2026, 8, 30, tzinfo=UTC))

    suggestions = suggest_posts(event, [older, newer], TZ)

    assert [s.post_id for s in suggestions] == ["p-newer", "p-older"]
    assert suggestions[0].score == suggestions[1].score
