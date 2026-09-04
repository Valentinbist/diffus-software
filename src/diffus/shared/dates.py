"""German month/weekday names shared by every bounded context.

Split out of shared/presentation/display.py so the calendar *application*
layer (the post-compose caption template, which needs weekday/month names
but must never import a presentation module) can depend on this instead.
shared/presentation/display.py re-exports both names, so nothing else in the
codebase has to change its imports.
"""

from __future__ import annotations

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
