"""Freigabe queue statistics, computed from the review log alone. Stdlib only.

The queue itself only ever shows what is still open (`GetReviewQueue`); it
never records how long something waited or how long the queue has sat
empty. `review_log` (`ReviewLogEntry`) does carry that: `queued_at` is when
a draft/post entered the queue, `at` is when a human decided it. This module
turns that append-only log into `ReviewStats` — the numbers the Freigabe
page's reaction-time and inbox-zero lines are built from.

The queue is only *provably* empty in the stretches between two decisions:
`[queued_at, at]` (or the point `[at]` when `queued_at` is unknown) is a
"busy" interval, and the gaps between merged busy intervals are the past
stretches with nothing queued. That is also why `inbox_zero_line`
(presentation/display.py) only ever shows `longest_empty`/`empty_since` while
the queue is empty *right now* — the log has nothing to say about whether
today's still-open stretch is the record until it, too, ends in a decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from diffus.crossposting.domain.entities import ReviewLogEntry, ReviewOutcome


@dataclass(frozen=True, slots=True)
class ReviewStats:
    decisions: int  # human decisions in total
    decided_today: int  # decisions with at >= day_start
    empty_since: datetime | None  # the newest decision's `at`; None without any decision
    longest_empty: timedelta | None  # longest PAST stretch with nothing queued
    mean_reaction: timedelta | None  # mean (at - queued_at) over decisions that know queued_at
    fastest_reaction: timedelta | None
    reactions: int  # how many decisions went into mean/fastest


@dataclass(frozen=True, slots=True)
class _Interval:
    start: datetime
    end: datetime


def _busy_interval(entry: ReviewLogEntry) -> _Interval:
    if entry.queued_at is not None and entry.queued_at <= entry.at:
        return _Interval(entry.queued_at, entry.at)
    return _Interval(entry.at, entry.at)


def _merge(intervals: Sequence[_Interval]) -> list[_Interval]:
    """Sorted by start, overlapping or touching intervals collapsed into one."""
    ordered = sorted(intervals, key=lambda i: i.start)
    merged: list[_Interval] = []
    for interval in ordered:
        if merged and interval.start <= merged[-1].end:
            if interval.end > merged[-1].end:
                merged[-1] = _Interval(merged[-1].start, interval.end)
        else:
            merged.append(interval)
    return merged


def review_stats(entries: Sequence[ReviewLogEntry], day_start: datetime) -> ReviewStats:
    # Defensive: the repository already filters to human decisions
    # (ReviewLogRepository.decisions), but never trust that from here too.
    human = (ReviewOutcome.APPROVED, ReviewOutcome.REJECTED)
    decisions = [e for e in entries if e.outcome in human]

    if not decisions:
        return ReviewStats(
            decisions=0,
            decided_today=0,
            empty_since=None,
            longest_empty=None,
            mean_reaction=None,
            fastest_reaction=None,
            reactions=0,
        )

    decided_today = sum(1 for e in decisions if e.at >= day_start)
    empty_since = max(e.at for e in decisions)

    merged = _merge([_busy_interval(e) for e in decisions])
    gaps = [b.start - a.end for a, b in zip(merged, merged[1:], strict=False)]
    longest_empty = max(gaps) if gaps else None

    reactions = [
        e.at - e.queued_at for e in decisions if e.queued_at is not None and e.queued_at <= e.at
    ]
    mean_reaction = sum(reactions, timedelta()) / len(reactions) if reactions else None
    fastest_reaction = min(reactions) if reactions else None

    return ReviewStats(
        decisions=len(decisions),
        decided_today=decided_today,
        empty_since=empty_since,
        longest_empty=longest_empty,
        mean_reaction=mean_reaction,
        fastest_reaction=fastest_reaction,
        reactions=len(reactions),
    )
