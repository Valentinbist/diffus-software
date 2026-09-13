from __future__ import annotations

from diffus.shared.automation import Streak


def test_a_fresh_streak_has_nothing_recorded():
    streak = Streak()

    assert streak.current == 0
    assert streak.best == 0
    assert streak.broken_at is None


def test_ok_runs_extend_the_current_streak_and_track_the_best():
    streak = Streak()

    streak = streak.record(True)
    streak = streak.record(True)
    streak = streak.record(True)

    assert streak.current == 3
    assert streak.best == 3
    assert streak.broken_at is None


def test_a_failure_resets_current_and_records_where_it_broke():
    streak = Streak(current=5, best=5)

    streak = streak.record(False)

    assert streak.current == 0
    assert streak.best == 5
    assert streak.broken_at == 5


def test_best_survives_a_later_failure():
    streak = Streak(current=10, best=10)
    streak = streak.record(False)

    streak = streak.record(True)
    streak = streak.record(True)

    assert streak.current == 2
    assert streak.best == 10
    assert streak.broken_at == 10


def test_record_returns_a_new_streak_without_mutating_the_original():
    original = Streak(current=1, best=1)

    updated = original.record(True)

    assert original.current == 1
    assert updated.current == 2
