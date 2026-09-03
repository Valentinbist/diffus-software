"""Date mentions inside free-form caption text ("📅 5. September").

Pure, stdlib only. Reused by the suggestion heuristic (`suggest_posts.py`) and,
later, by a post→event wizard that prefills an event's date from a caption.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# Numeric "05.09", "5.9.", "05.09.2026", "5.9.26" — but not "18.30 Uhr" (a
# time, not a date) or "19.00" once month range validation runs.
_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.?(?:\s?(\d{4}|\d{2}))?(?!\s*Uhr)(?!\d)", re.IGNORECASE
)

# Textual "5. September", "5.Sept.", "05 Sep 2026". The month alternation is
# ordered short-to-long; the trailing \b only accepts a match at a real word
# boundary, so it backtracks past "sep"/"sept" onto "september" for the full
# word instead of stopping short.
_TEXTUAL = re.compile(
    r"(\d{1,2})\.?\s*"
    r"(jan|januar|feb|februar|mär|märz|maerz|apr|april|mai|jun|juni|jul|juli|"
    r"aug|august|sep|sept|september|okt|oktober|nov|november|dez|dezember)\b\.?"
    r"(?:\s*(\d{4}))?",
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1,
    "januar": 1,
    "feb": 2,
    "februar": 2,
    "mär": 3,
    "märz": 3,
    "maerz": 3,
    "apr": 4,
    "april": 4,
    "mai": 5,
    "jun": 6,
    "juni": 6,
    "jul": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dez": 12,
    "dezember": 12,
}


@dataclass(frozen=True, slots=True)
class DateMention:
    day: int
    month: int
    year: int | None


def _year_from(text: str | None) -> int | None:
    if text is None:
        return None
    return 2000 + int(text) if len(text) == 2 else int(text)


def find_date_mentions(text: str | None) -> list[DateMention]:
    """Every day.month(.year) or day-month-name(-year) mention in `text`, in reading order."""
    if not text:
        return []

    found: list[tuple[int, DateMention]] = []
    for match in _NUMERIC.finditer(text):
        day, month = int(match.group(1)), int(match.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            continue
        mention = DateMention(day=day, month=month, year=_year_from(match.group(3)))
        found.append((match.start(), mention))

    for match in _TEXTUAL.finditer(text):
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).lower())
        if month is None or not (1 <= day <= 31):
            continue
        mention = DateMention(day=day, month=month, year=_year_from(match.group(3)))
        found.append((match.start(), mention))

    found.sort(key=lambda pair: pair[0])
    return [mention for _start, mention in found]


def resolve_mention(mention: DateMention, around: date) -> date | None:
    """The calendar date this mention most plausibly refers to, or None for an invalid day/month.

    An explicit year wins outright. Without one, the same day/month can fall
    in the year before, the same year, or the year after `around` (a caption
    written in late December about "5. Januar" means next January) — pick
    whichever of those is closest to `around`.
    """
    if mention.year is not None:
        try:
            return date(mention.year, mention.month, mention.day)
        except ValueError:
            return None

    candidates = []
    for year in (around.year - 1, around.year, around.year + 1):
        try:
            candidates.append(date(year, mention.month, mention.day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - around).days))
