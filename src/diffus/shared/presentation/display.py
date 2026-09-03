"""Formatting shared across bounded contexts: German, human-scale time and text helpers.

Pure functions that take `now` explicitly so they are trivially testable. Wired
into Jinja as filters by shared/presentation/templates.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

# Error strings come from httpx and quote the request URL, which carries the
# Instagram access token / Telegram bot token / kalender.digital capability
# token as part of the path or query.
_SECRET_PATTERNS = (
    re.compile(r"(access_token=)[^&\s'\"]+"),
    re.compile(r"(client_secret=)[^&\s'\"]+"),
    re.compile(r"(/bot)\d+:[\w-]+"),
    re.compile(r"(capabilityId=)[^&\s'\"]+"),
)


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


def summary(text: str | None, limit: int = 90) -> str:
    """First non-empty line of a caption, cut to `limit` characters."""
    if not text:
        return ""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(line) <= limit:
        return line
    return line[: limit - 1].rstrip() + "…"


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1…", text)
    return text


def error_text(text: str | None, limit: int = 160) -> str:
    """An error message safe to put on the page: secrets stripped, one line, short."""
    return summary(redact(text or ""), limit)
