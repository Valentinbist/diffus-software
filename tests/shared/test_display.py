from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.shared.automation import Streak
from diffus.shared.presentation.display import (
    EMPTY_LINES,
    MILESTONES,
    count_since,
    day_start,
    empty_line,
    error_text,
    format_ago,
    format_day,
    format_duration,
    format_until,
    format_when,
    greeting,
    heatmap,
    milestone,
    streak_line,
    summary,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin (CEST)


def test_when_today_yesterday_and_older():
    assert format_when(datetime(2026, 9, 3, 8, 22, tzinfo=UTC), NOW, TZ) == "Heute, 10:22"
    assert format_when(datetime(2026, 9, 2, 17, 3, tzinfo=UTC), NOW, TZ) == "Gestern, 19:03"
    assert format_when(datetime(2026, 8, 28, 9, 40, tzinfo=UTC), NOW, TZ) == "28. August, 11:40"


def test_when_adds_the_year_only_outside_the_current_one():
    assert format_when(datetime(2025, 12, 24, 11, 0, tzinfo=UTC), NOW, TZ) == (
        "24. Dezember 2025, 12:00"
    )


def test_day_boundary_follows_the_display_zone_not_utc():
    # 22:30 UTC on the 2nd is already 00:30 on the 3rd in Berlin.
    assert format_when(datetime(2026, 9, 2, 22, 30, tzinfo=UTC), NOW, TZ) == "Heute, 00:30"
    assert format_day(datetime(2026, 9, 2, 22, 30, tzinfo=UTC), NOW, TZ) == "Heute"


def test_ago_picks_the_largest_sensible_unit():
    assert format_ago(NOW - timedelta(seconds=30), NOW) == "gerade eben"
    assert format_ago(NOW - timedelta(minutes=1), NOW) == "vor 1 Minute"
    assert format_ago(NOW - timedelta(minutes=4), NOW) == "vor 4 Minuten"
    assert format_ago(NOW - timedelta(hours=2), NOW) == "vor 2 Stunden"
    assert format_ago(NOW - timedelta(days=3), NOW) == "vor 3 Tagen"
    assert format_ago(NOW + timedelta(minutes=5), NOW) == "gerade eben"  # clock skew, not future


def test_until_picks_the_largest_sensible_unit():
    assert format_until(NOW + timedelta(seconds=30), NOW) == "gleich"
    assert format_until(NOW + timedelta(minutes=1), NOW) == "in 1 Minute"
    assert format_until(NOW + timedelta(minutes=4), NOW) == "in 4 Minuten"
    assert format_until(NOW + timedelta(hours=2), NOW) == "in 2 Stunden"
    assert format_until(NOW + timedelta(days=3), NOW) == "in 3 Tagen"
    assert format_until(NOW - timedelta(minutes=5), NOW) == "gleich"  # already due, not negative


def test_summary_takes_the_first_real_line_and_truncates():
    assert summary(None) == ""
    assert summary("  \nSiebdruck-Nachmittag! 🧵\n📅 5. September") == "Siebdruck-Nachmittag! 🧵"
    cut = summary("x" * 200, limit=90)
    assert len(cut) == 90
    assert cut.endswith("…")


def test_error_text_strips_tokens_from_quoted_urls():
    ig = "400 for url 'https://graph.instagram.com/me/media?fields=id&access_token=IGQVJ123'"
    tg = "401 for url 'https://api.telegram.org/bot123456:ABC-def_9/sendPhoto'"

    assert "IGQVJ123" not in error_text(ig)
    assert "access_token=…" in error_text(ig)
    assert "123456:ABC-def_9" not in error_text(tg)
    assert "/bot…/sendPhoto" in error_text(tg)


def test_streak_line_singular_and_plural():
    assert streak_line(Streak(current=1)) == "Serie: 1 Lauf ohne Fehler."
    assert streak_line(Streak(current=37)) == "Serie: 37 Läufe ohne Fehler."


def test_streak_line_appends_the_record_only_when_better_than_current():
    assert streak_line(Streak(current=37, best=120)) == "Serie: 37 Läufe ohne Fehler. Rekord: 120."
    assert streak_line(Streak(current=37, best=37)) == "Serie: 37 Läufe ohne Fehler."


def test_streak_line_reports_where_it_broke_when_nothing_is_running():
    assert streak_line(Streak(current=0, broken_at=37)) == "Serie gerissen bei 37."


def test_streak_line_is_none_before_any_run_or_failure():
    assert streak_line(Streak()) is None


def test_error_text_strips_the_kalender_digital_capability_token():
    kd = (
        "500 for url 'https://api.kalender.digital/event?capabilityId="
        "03e3bc8e2be173ff9c8b&startDate=2026-06-01&endDate=2027-03-31'"
    )

    assert "03e3bc8e2be173ff9c8b" not in error_text(kd)
    assert "capabilityId=…" in error_text(kd)


# -- format_duration -----------------------------------------------------------


def test_duration_under_a_minute():
    assert format_duration(timedelta(seconds=30)) == "unter einer Minute"


def test_duration_minutes_singular_and_plural():
    assert format_duration(timedelta(minutes=1)) == "1 Minute"
    assert format_duration(timedelta(minutes=12)) == "12 Minuten"


def test_duration_hours_with_and_without_a_remainder():
    assert format_duration(timedelta(hours=2)) == "2 h"
    assert format_duration(timedelta(hours=2, minutes=10)) == "2 h 10 min"


def test_duration_days_singular_and_plural_nominative_vs_dative():
    assert format_duration(timedelta(days=1)) == "1 Tag"
    assert format_duration(timedelta(days=3)) == "3 Tage"
    assert format_duration(timedelta(days=3), dative=True) == "3 Tagen"
    assert format_duration(timedelta(days=1), dative=True) == "1 Tag"  # singular unaffected


# -- greeting --------------------------------------------------------------------


def test_greeting_says_good_morning_in_its_window():
    morning = NOW.astimezone(TZ).replace(hour=7).astimezone(UTC)
    assert greeting(morning, TZ) == "Guten Morgen."


def test_greeting_asks_about_the_night_shift_late_and_early():
    late = NOW.astimezone(TZ).replace(hour=23).astimezone(UTC)
    early = NOW.astimezone(TZ).replace(hour=3).astimezone(UTC)
    assert greeting(late, TZ) == "Nachtschicht?"
    assert greeting(early, TZ) == "Nachtschicht?"


def test_greeting_is_none_outside_both_windows():
    assert greeting(NOW, TZ) is None  # 12:00 Berlin


# -- empty_line ------------------------------------------------------------------


def test_empty_line_is_stable_for_the_whole_local_day():
    morning = NOW.astimezone(TZ).replace(hour=1).astimezone(UTC)
    evening = NOW.astimezone(TZ).replace(hour=23).astimezone(UTC)

    assert empty_line(morning, TZ) == empty_line(evening, TZ)
    assert empty_line(NOW, TZ) in EMPTY_LINES


def test_empty_line_changes_on_a_different_day():
    tomorrow = NOW + timedelta(days=1)

    assert empty_line(NOW, TZ) != empty_line(tomorrow, TZ)


# -- milestone -------------------------------------------------------------------


def test_milestones_are_the_documented_round_numbers():
    assert MILESTONES == (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def test_milestone_is_none_when_nothing_happened_today():
    assert milestone(total=100, today=0) is None


def test_milestone_picks_the_largest_number_crossed_today():
    assert milestone(total=12, today=3) == 10  # 10, 11, 12 happened today
    assert milestone(total=30, today=25) == 25  # both 10 and 25 happened today


def test_milestone_is_none_when_no_round_number_was_crossed():
    assert milestone(total=9, today=3) is None


# -- day_start / count_since ------------------------------------------------------


def test_day_start_is_local_midnight_as_aware_utc():
    assert day_start(NOW, TZ) == datetime(2026, 9, 2, 22, 0, tzinfo=UTC)  # 00:00 CEST


def test_count_since_counts_stamps_at_or_after_the_cutoff():
    since = datetime(2026, 1, 2, tzinfo=UTC)
    stamps = [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    ]

    assert count_since(stamps, since) == 2


# -- heatmap ---------------------------------------------------------------------


def test_heatmap_windows_by_local_monday_to_sunday_weeks_ending_this_week():
    grid = heatmap([], NOW, TZ, weeks=2)

    assert len(grid.weeks) == 2
    assert all(len(week) == 7 for week in grid.weeks)
    assert grid.weeks[0][0].day == date(2026, 8, 24)  # Monday, 2 weeks back
    assert grid.weeks[1][6].day == date(2026, 9, 6)  # Sunday of this week
    assert grid.total == 0
    assert grid.busiest == 0


def test_heatmap_counts_stamps_by_local_day_and_levels_them():
    stamps = [
        datetime(2026, 8, 25, 6, 0, tzinfo=UTC),
        datetime(2026, 8, 25, 20, 0, tzinfo=UTC),  # same local day: count 2
        datetime(2026, 9, 1, 5, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 19, 0, tzinfo=UTC),  # count 3 -> level caps at 3
    ]

    grid = heatmap(stamps, NOW, TZ, weeks=2)

    by_day = {d.day: d for week in grid.weeks for d in week}
    assert by_day[date(2026, 8, 25)].count == 2
    assert by_day[date(2026, 8, 25)].level == 2
    assert by_day[date(2026, 9, 1)].count == 3
    assert by_day[date(2026, 9, 1)].level == 3
    assert grid.total == 5
    assert grid.busiest == 3


def test_heatmap_ignores_stamps_outside_the_window():
    outside = [datetime(2026, 8, 1, tzinfo=UTC)]

    grid = heatmap(outside, NOW, TZ, weeks=2)

    assert grid.total == 0


def test_heatmap_marks_days_after_today_as_future():
    grid = heatmap([], NOW, TZ, weeks=2)

    by_day = {d.day: d for week in grid.weeks for d in week}
    assert by_day[date(2026, 9, 3)].future is False  # today itself
    assert by_day[date(2026, 9, 4)].future is True
    assert by_day[date(2026, 9, 6)].future is True


def test_heatmap_label_is_never_heute_and_carries_the_year_outside_the_current_one():
    grid = heatmap([], NOW, TZ, weeks=2)

    by_day = {d.day: d for week in grid.weeks for d in week}
    assert by_day[date(2026, 9, 3)].label == "3. September"  # today, but never "Heute"
    assert by_day[date(2026, 8, 25)].label == "25. August"  # no year: current year


def test_heatmap_label_carries_the_year_when_the_window_spans_a_year_boundary():
    new_year_now = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)

    grid = heatmap([], new_year_now, TZ, weeks=2)

    by_day = {d.day: d for week in grid.weeks for d in week}
    assert by_day[date(2025, 12, 29)].label == "29. Dezember 2025"
