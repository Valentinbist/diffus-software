"""review_stats: turns the append-only review log into the Freigabe stats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from diffus.crossposting.domain.entities import Destination, ReviewLogEntry, ReviewOutcome
from diffus.crossposting.domain.stats import review_stats

DAY_START = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
TELEGRAM = Destination("telegram", "c1")


def make_entry(
    at: datetime,
    queued_at: datetime | None = None,
    outcome: ReviewOutcome = ReviewOutcome.APPROVED,
) -> ReviewLogEntry:
    return ReviewLogEntry.new(
        "post", outcome, "caption", (TELEGRAM,), at, post_id="p1", queued_at=queued_at
    )


def test_empty_input_has_no_decisions_and_nothing_computed():
    stats = review_stats([], DAY_START)

    assert stats.decisions == 0
    assert stats.decided_today == 0
    assert stats.empty_since is None
    assert stats.longest_empty is None
    assert stats.mean_reaction is None
    assert stats.fastest_reaction is None
    assert stats.reactions == 0


def test_a_single_decision():
    at = DAY_START + timedelta(hours=2)
    queued_at = at - timedelta(minutes=5)

    stats = review_stats([make_entry(at, queued_at)], DAY_START)

    assert stats.decisions == 1
    assert stats.decided_today == 1
    assert stats.empty_since == at
    assert stats.longest_empty is None  # only one busy interval: no gap to measure
    assert stats.mean_reaction == timedelta(minutes=5)
    assert stats.fastest_reaction == timedelta(minutes=5)
    assert stats.reactions == 1


def test_two_items_queued_together_but_decided_apart_merge_with_no_gap():
    queued_at = DAY_START + timedelta(hours=1)
    first = make_entry(queued_at + timedelta(minutes=10), queued_at)
    second = make_entry(queued_at + timedelta(minutes=20), queued_at)

    stats = review_stats([first, second], DAY_START)

    assert stats.decisions == 2
    assert stats.longest_empty is None  # overlapping busy intervals merge into one


def test_a_gap_between_two_separate_busy_intervals_is_the_longest_empty():
    first_queued = DAY_START + timedelta(hours=1)
    first_at = first_queued + timedelta(minutes=10)
    second_queued = first_at + timedelta(minutes=50)  # the gap
    second_at = second_queued + timedelta(minutes=5)

    stats = review_stats(
        [make_entry(first_at, first_queued), make_entry(second_at, second_queued)], DAY_START
    )

    assert stats.longest_empty == timedelta(minutes=50)


def test_the_largest_of_several_gaps_wins():
    base = DAY_START + timedelta(hours=1)
    a = make_entry(base, base)
    b = make_entry(base + timedelta(hours=1), base + timedelta(hours=1))  # 1h gap after a
    c = make_entry(base + timedelta(hours=4), base + timedelta(hours=4))  # 3h gap after b

    stats = review_stats([a, b, c], DAY_START)

    assert stats.longest_empty == timedelta(hours=3)


def test_entries_without_queued_at_count_as_points_not_intervals():
    at = DAY_START + timedelta(hours=1)

    stats = review_stats([make_entry(at, queued_at=None)], DAY_START)

    assert stats.decisions == 1
    assert stats.reactions == 0  # no queued_at: not a measurable reaction
    assert stats.mean_reaction is None
    assert stats.fastest_reaction is None


def test_a_point_entry_still_creates_a_gap_against_its_neighbours():
    base = DAY_START + timedelta(hours=1)
    point = make_entry(base, queued_at=None)
    later = make_entry(base + timedelta(hours=2), queued_at=base + timedelta(hours=2))

    stats = review_stats([point, later], DAY_START)

    assert stats.longest_empty == timedelta(hours=2)


def test_mean_and_fastest_reaction_over_several_decisions():
    base = DAY_START + timedelta(hours=1)
    fast = make_entry(base, base - timedelta(minutes=2))
    slow = make_entry(base + timedelta(hours=1), base + timedelta(hours=1) - timedelta(minutes=18))
    no_queue = make_entry(base + timedelta(hours=2), queued_at=None)

    stats = review_stats([fast, slow, no_queue], DAY_START)

    assert stats.reactions == 2
    assert stats.fastest_reaction == timedelta(minutes=2)
    assert stats.mean_reaction == timedelta(minutes=10)


def test_decided_today_counts_only_entries_at_or_after_day_start():
    yesterday = make_entry(DAY_START - timedelta(hours=1), DAY_START - timedelta(hours=2))
    today = make_entry(DAY_START + timedelta(minutes=1), DAY_START)

    stats = review_stats([yesterday, today], DAY_START)

    assert stats.decisions == 2
    assert stats.decided_today == 1


def test_queued_at_after_at_is_treated_as_unknown_not_negative():
    at = DAY_START + timedelta(hours=1)
    backwards = make_entry(at, queued_at=at + timedelta(minutes=5))

    stats = review_stats([backwards], DAY_START)

    assert stats.reactions == 0
    assert stats.mean_reaction is None
