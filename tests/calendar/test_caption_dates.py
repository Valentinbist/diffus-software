"""caption_dates: pattern matching and nearest-year resolution for date mentions in captions."""

from __future__ import annotations

from datetime import date

from diffus.calendar.application.caption_dates import (
    DateMention,
    find_date_mentions,
    resolve_mention,
)


def test_numeric_dates_in_various_shapes_are_recognised():
    assert find_date_mentions("05.09.") == [DateMention(day=5, month=9, year=None)]
    assert find_date_mentions("5.9.2026") == [DateMention(day=5, month=9, year=2026)]
    assert find_date_mentions("5.9.26") == [DateMention(day=5, month=9, year=2026)]


def test_textual_dates_in_various_shapes_are_recognised():
    assert find_date_mentions("📅 5. September") == [DateMention(day=5, month=9, year=None)]
    assert find_date_mentions("Sa 5. Sept.") == [DateMention(day=5, month=9, year=None)]
    assert find_date_mentions("05 Sep 2026") == [DateMention(day=5, month=9, year=2026)]


def test_a_time_that_looks_like_a_date_is_not_mistaken_for_one():
    assert find_date_mentions("18.30 Uhr") == []
    assert find_date_mentions("19.00") == []


def test_no_text_yields_no_mentions():
    assert find_date_mentions(None) == []
    assert find_date_mentions("") == []


def test_a_calendar_impossible_day_month_is_still_reported_as_a_raw_mention():
    # Whether 30.02. is a real date is resolve_mention's job, not the pattern's.
    assert find_date_mentions("30.02.") == [DateMention(day=30, month=2, year=None)]


def test_resolve_mention_picks_the_year_closest_to_the_post_date_when_none_is_given():
    # A caption written in late December about "5. Januar" means next January.
    mention = DateMention(day=5, month=1, year=None)
    assert resolve_mention(mention, around=date(2026, 12, 20)) == date(2027, 1, 5)

    mention2 = DateMention(day=28, month=8, year=None)
    assert resolve_mention(mention2, around=date(2026, 9, 3)) == date(2026, 8, 28)


def test_resolve_mention_prefers_an_explicit_year_over_the_nearest_one():
    mention = DateMention(day=5, month=1, year=2030)
    assert resolve_mention(mention, around=date(2026, 12, 20)) == date(2030, 1, 5)


def test_resolve_mention_returns_none_for_an_impossible_day_month_combination():
    assert resolve_mention(DateMention(day=30, month=2, year=None), around=date(2026, 9, 3)) is None
    assert resolve_mention(DateMention(day=30, month=2, year=2026), around=date(2026, 9, 3)) is None
