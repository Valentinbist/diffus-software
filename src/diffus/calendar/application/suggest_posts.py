"""The event↔post suggestion heuristic: which posts might announce a given event,
and the reverse — which events a given post might announce.

Pure, stdlib only (plus ZoneInfo). Both directions score the same three
signals (`_score`) for one event/post pair; `suggest_posts` and
`suggest_events` just iterate the candidates from opposite sides.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo

from diffus.calendar.application.caption_dates import find_date_mentions, resolve_mention
from diffus.calendar.domain.entities import CalendarEvent, LinkablePost

WINDOW_DAYS = 14
MIN_WORD = 4

STOPWORDS = frozenset(
    {
        "und",
        "oder",
        "der",
        "die",
        "das",
        "mit",
        "für",
        "von",
        "zum",
        "zur",
        "eine",
        "einen",
        "einer",
        "offen",
        "raum",
        "alle",
    }
)

_WORD = re.compile(r"\w+")


class SuggestionReason(StrEnum):
    DATE = "date"
    TITLE = "title"
    RECENT = "recent"


@dataclass(frozen=True, slots=True)
class Suggestion:
    post_id: str
    score: int
    reasons: tuple[SuggestionReason, ...]


@dataclass(frozen=True, slots=True)
class EventSuggestion:
    event_id: str
    score: int
    reasons: tuple[SuggestionReason, ...]


def _significant_words(text: str | None) -> set[str]:
    if not text:
        return set()
    return {w for w in _WORD.findall(text.lower()) if len(w) >= MIN_WORD and w not in STOPWORDS}


def _score(
    event: CalendarEvent, post: LinkablePost, tz: ZoneInfo
) -> tuple[int, tuple[SuggestionReason, ...]]:
    """Score one event/post pair: a caption date mention beats a title overlap beats recency."""
    event_days = set(event.local_days(tz))
    event_start_day = event.starts_at.astimezone(tz).date()
    title_words = _significant_words(event.title)

    score = 0
    reasons: list[SuggestionReason] = []

    posted_day = post.posted_at.astimezone(tz).date()
    mentions = find_date_mentions(post.caption)
    if any(
        (resolved := resolve_mention(mention, around=posted_day)) is not None
        and resolved in event_days
        for mention in mentions
    ):
        score += 3
        reasons.append(SuggestionReason.DATE)

    overlap = title_words & _significant_words(post.caption)
    if overlap:
        score += min(len(overlap), 2)
        reasons.append(SuggestionReason.TITLE)

    if 0 <= (event_start_day - posted_day).days <= WINDOW_DAYS:
        score += 1
        reasons.append(SuggestionReason.RECENT)

    return score, tuple(reasons)


def suggest_posts(
    event: CalendarEvent, posts: Sequence[LinkablePost], tz: ZoneInfo, limit: int = 5
) -> list[Suggestion]:
    """Candidate posts for this event, best match first."""
    scored: list[tuple[Suggestion, LinkablePost]] = []
    for post in posts:
        score, reasons = _score(event, post, tz)
        if score > 0:
            scored.append((Suggestion(post_id=post.id, score=score, reasons=reasons), post))

    scored.sort(key=lambda pair: (-pair[0].score, -pair[1].posted_at.timestamp()))
    return [suggestion for suggestion, _post in scored[:limit]]


def suggest_events(
    post: LinkablePost, events: Sequence[CalendarEvent], tz: ZoneInfo, limit: int = 5
) -> list[EventSuggestion]:
    """Candidate events for this post, best match first — the link-picker's other direction."""
    scored: list[tuple[EventSuggestion, CalendarEvent]] = []
    for event in events:
        score, reasons = _score(event, post, tz)
        if score > 0:
            scored.append((EventSuggestion(event_id=event.id, score=score, reasons=reasons), event))

    scored.sort(key=lambda pair: (-pair[0].score, pair[1].starts_at))
    return [suggestion for suggestion, _event in scored[:limit]]
