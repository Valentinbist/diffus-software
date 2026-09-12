"""Context-neutral view of "what runs on a timer", for the /einstellungen page.

Each context (crossposting, calendar) keeps its own job/run history — see
crossposting/application/sync_job.py and calendar/application/sync_job.py —
and translates it into a `JobStatus` via its own `presentation/display.py`
(`job_status`). This module only holds the shape the settings page renders,
so neither context's presentation layer has to import the other's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

# How many past runs each job keeps, newest first — enough for "Letzte Läufe"
# without the list growing unbounded. Value-only, so crossposting/calendar's
# application layers may import this module the same way they already import
# shared.dates (see docs/architecture.md, Layout).
RUN_HISTORY = 10


@dataclass(frozen=True, slots=True)
class JobRun:
    """One past run of a job. A None error means that run went through."""

    at: datetime
    error: str | None = None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class JobStatus:
    """One job's status, as the settings page shows it: label, history, and its own sync button."""

    key: str
    label: str
    runs: tuple[JobRun, ...]
    sync_action: str

    @property
    def last(self) -> JobRun | None:
        return self.runs[0] if self.runs else None


@dataclass(frozen=True, slots=True)
class Automation:
    """The settings page's whole "Automatik" section: the interval, and every job on it.

    `jobs`/`next_run` are callables rather than plain values because a job's
    runs and the scheduler's next fire time change between requests — the
    settings route calls them fresh each time it renders.
    """

    interval_minutes: int
    jobs: Callable[[], Sequence[JobStatus]]
    next_run: Callable[[], datetime | None]
