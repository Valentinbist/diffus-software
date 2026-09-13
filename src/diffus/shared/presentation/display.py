"""Formatting shared across bounded contexts: German, human-scale time and text helpers.

Pure functions that take `now` explicitly so they are trivially testable. Wired
into Jinja as filters by shared/presentation/templates.py. `redact` lives in
`diffus.shared.redact` (a presentation module is the wrong layer for
infrastructure adapters to depend on) and is re-exported here so `error_text`
and existing callers/tests keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.shared.automation import Streak
from diffus.shared.dates import MONTHS, WEEKDAYS
from diffus.shared.redact import redact

__all__ = [
    "MONTHS",
    "WEEKDAYS",
    "format_day",
    "format_when",
    "format_ago",
    "format_until",
    "format_duration",
    "summary",
    "redact",
    "error_text",
    "streak_line",
    "greeting",
    "EMPTY_LINES",
    "empty_line",
    "MILESTONES",
    "milestone",
    "day_start",
    "count_since",
    "HeatmapDay",
    "Heatmap",
    "heatmap",
]


def format_day(dt: datetime, now: datetime, tz: ZoneInfo) -> str:
    """'Heute', 'Gestern', '28. August', or '28. August 2025' outside the current year."""
    day = dt.astimezone(tz).date()
    today = now.astimezone(tz).date()
    if day == today:
        return "Heute"
    if day == today - timedelta(days=1):
        return "Gestern"
    text = f"{day.day}. {MONTHS[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year}"
    return text


def format_when(dt: datetime, now: datetime, tz: ZoneInfo) -> str:
    """'Heute, 14:22' — the timestamp style of the mockups."""
    return f"{format_day(dt, now, tz)}, {dt.astimezone(tz):%H:%M}"


def format_ago(dt: datetime, now: datetime) -> str:
    """'gerade eben', 'vor 4 Minuten', 'vor 2 Stunden', 'vor 3 Tagen'."""
    seconds = max((now - dt).total_seconds(), 0)
    if seconds < 60:
        return "gerade eben"
    minutes = int(seconds // 60)
    if minutes < 60:
        return "vor 1 Minute" if minutes == 1 else f"vor {minutes} Minuten"
    hours = minutes // 60
    if hours < 24:
        return "vor 1 Stunde" if hours == 1 else f"vor {hours} Stunden"
    days = hours // 24
    return "vor 1 Tag" if days == 1 else f"vor {days} Tagen"


def format_until(dt: datetime, now: datetime) -> str:
    """'gleich', 'in 1 Minute', 'in 4 Minuten', 'in 2 Stunden', 'in 3 Tagen' — format_ago's mirror.

    Used for a scheduled future time (the settings page's "Nächster Lauf"),
    never a past one — a negative delta (dt already passed) still reads as
    "gleich" rather than a nonsensical negative count.
    """
    seconds = max((dt - now).total_seconds(), 0)
    if seconds < 60:
        return "gleich"
    minutes = int(seconds // 60)
    if minutes < 60:
        return "in 1 Minute" if minutes == 1 else f"in {minutes} Minuten"
    hours = minutes // 60
    if hours < 24:
        return "in 1 Stunde" if hours == 1 else f"in {hours} Stunden"
    days = hours // 24
    return "in 1 Tag" if days == 1 else f"in {days} Tagen"


def format_duration(td: timedelta, dative: bool = False) -> str:
    """'unter einer Minute', '1 Minute'/'N Minuten', '2 h'/'2 h 10 min', '3 Tage'/dative '3 Tagen'.

    Unlike format_ago/format_until (a point in time relative to now), this
    formats a duration itself — the Freigabe reaction time ("Entschieden
    nach {duration}") and record ("Rekord: {duration}"). `dative` only ever
    changes the days branch's plural ("Tage" -> "Tagen"): every other branch
    already reads the same in both cases, the same way format_ago says
    "vor 1 Tag" rather than "vor einem Tag".
    """
    seconds = max(td.total_seconds(), 0)
    if seconds < 60:
        return "unter einer Minute"
    minutes = int(seconds // 60)
    if minutes < 60:
        return "1 Minute" if minutes == 1 else f"{minutes} Minuten"
    hours = minutes // 60
    if hours < 24:
        rest = minutes % 60
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    days = hours // 24
    if days == 1:
        return "1 Tag"
    return f"{days} Tagen" if dative else f"{days} Tage"


def summary(text: str | None, limit: int = 90) -> str:
    """First non-empty line of a caption, cut to `limit` characters."""
    if not text:
        return ""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(line) <= limit:
        return line
    return line[: limit - 1].rstrip() + "…"


def error_text(text: str | None, limit: int = 160) -> str:
    """An error message safe to put on the page: secrets stripped, one line, short."""
    return summary(redact(text or ""), limit)


def streak_line(streak: Streak) -> str | None:
    """The settings page's per-job streak line, or None when there's nothing to say yet."""
    if streak.current > 0:
        run_word = "Lauf" if streak.current == 1 else "Läufe"
        line = f"Serie: {streak.current} {run_word} ohne Fehler."
        if streak.best > streak.current:
            line += f" Rekord: {streak.best}."
        return line
    if streak.broken_at:
        return f"Serie gerissen bei {streak.broken_at}."
    return None


def greeting(now: datetime, tz: ZoneInfo) -> str | None:
    """A one-off kicker line on the index page, or None outside its two windows."""
    hour = now.astimezone(tz).hour
    if 5 <= hour <= 9:
        return "Guten Morgen."
    if hour == 23 or hour <= 4:
        return "Nachtschicht?"
    return None


# Dry one-liners for an empty Freigabe queue — picked by day of year (empty_line)
# so the same day always shows the same line rather than reshuffling on every
# request, without needing anywhere to store which lines were shown already.
EMPTY_LINES: tuple[str, ...] = (
    "Geh raus, es ist schön draußen.",
    "Die Warteschlange macht Pause.",
    "Kein Post wartet. Du auch nicht.",
    "Alles draußen, nichts drin.",
    "Nichts liegt an. Das ist auch eine Nachricht.",
    "Die Freigabe hat Feierabend.",
    "Hier könnte dein Post warten. Tut er aber nicht.",
    "Stille im Postfach.",
    "Zeit für einen Kaffee.",
    "Heute nichts zu entscheiden. Genieß es.",
    "Alles freigegeben. Alles gut.",
    "Leer. Schön leer.",
)


def empty_line(now: datetime, tz: ZoneInfo) -> str:
    """One of EMPTY_LINES, stable for the whole local day."""
    day_of_year = now.astimezone(tz).timetuple().tm_yday
    return EMPTY_LINES[day_of_year % len(EMPTY_LINES)]


# Round numbers worth calling out on the index/Freigabe "Post Nummer N" line.
MILESTONES: tuple[int, ...] = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def milestone(total: int, today: int) -> int | None:
    """The milestone crossed today, or None: the largest M with total - today < M <= total."""
    if today == 0:
        return None
    reached = [m for m in MILESTONES if total - today < m <= total]
    return max(reached) if reached else None


def day_start(now: datetime, tz: ZoneInfo) -> datetime:
    """Local midnight of `now`'s local day, as an aware UTC datetime."""
    local_midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


def count_since(stamps: Iterable[datetime], since: datetime) -> int:
    return sum(1 for stamp in stamps if stamp >= since)


@dataclass(frozen=True, slots=True)
class HeatmapDay:
    day: date
    count: int
    level: int  # 0 none, 1, 2, 3 = three or more
    future: bool  # after today (rendered invisible)
    label: str  # "12. August", with the year appended outside the current year — never "Heute"


@dataclass(frozen=True, slots=True)
class Heatmap:
    weeks: tuple[tuple[HeatmapDay, ...], ...]  # 16 columns oldest first, each Monday..Sunday
    total: int  # posts inside the window
    busiest: int  # most posts on one day


def heatmap(stamps: Iterable[datetime], now: datetime, tz: ZoneInfo, weeks: int = 16) -> Heatmap:
    """The index page's activity heatmap: `weeks` local Mon-Sun weeks ending with this one.

    Only `stamps` that fall on a local day inside the window count towards
    `total`/`busiest`/each day's `count` — a caller may hand in a slightly
    wider range (GetActivity's own cutoff has some slack) without it leaking
    into what the grid reports.
    """
    today = now.astimezone(tz).date()
    week_end = today + timedelta(days=6 - today.weekday())  # Sunday of today's week
    week_start = week_end - timedelta(days=7 * weeks - 1)  # Monday, `weeks` weeks back

    counts: dict[date, int] = {}
    for stamp in stamps:
        day = stamp.astimezone(tz).date()
        if week_start <= day <= week_end:
            counts[day] = counts.get(day, 0) + 1

    days: list[HeatmapDay] = []
    day = week_start
    while day <= week_end:
        count = counts.get(day, 0)
        label = f"{day.day}. {MONTHS[day.month - 1]}"
        if day.year != today.year:
            label += f" {day.year}"
        days.append(
            HeatmapDay(day=day, count=count, level=min(count, 3), future=day > today, label=label)
        )
        day += timedelta(days=1)

    grid: tuple[tuple[HeatmapDay, ...], ...] = tuple(
        tuple(days[i : i + 7]) for i in range(0, len(days), 7)
    )
    return Heatmap(
        weeks=grid,
        total=sum(d.count for d in days),
        busiest=max((d.count for d in days), default=0),
    )
