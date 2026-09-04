"""Dates the mocks agree on.

The Instagram mock seeds a post whose caption names a date, and the
kalender.digital mock seeds an event on that same date, so the calendar's
link-suggestion heuristic (caption date == event day) has a real match to
find. Both compute the date here instead of each hard-coding one, so they can
never drift apart: the 12th of next month, whichever month the mocks run in.
"""

from __future__ import annotations

from datetime import date, timedelta

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


def siebdruck_day(today: date) -> date:
    """The 12th of the month after `today`."""
    next_month_first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return next_month_first.replace(day=12)


def german_date(day: date) -> str:
    """'12. Oktober' — the form the caption-date heuristic recognises."""
    return f"{day.day}. {MONTHS[day.month - 1]}"
