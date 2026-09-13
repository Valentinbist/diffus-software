"""The calendar's own periodic sync job.

The calendar rides the same single scheduler tick as crossposting rather than
getting a second `add_job`: an APScheduler interval trigger fires one
interval after process start (see docs/architecture.md, Sharp edges), so a
second interval job would just reproduce that same startup gap for no
benefit. The composition root instead runs `SyncJob.run()` and
`CalendarSyncJob.run()` in sequence inside one tick (`app.py`).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from diffus.calendar.application.sync_calendar import CalendarSyncReport, SyncCalendar
from diffus.shared.automation import RUN_HISTORY, Streak

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalendarLastRun:
    """What the UI shows about one calendar sync. A None error means it went through."""

    at: datetime
    error: str | None = None
    # The report the sync produced on success; None on error.
    report: CalendarSyncReport | None = None


class CalendarSyncJob:
    """Serialises calendar syncs so the scheduler and a manual trigger can't overlap."""

    def __init__(self, sync: SyncCalendar) -> None:
        self.sync = sync
        self.lock = asyncio.Lock()
        # In-memory on purpose: it answers "is the calendar sync alive?",
        # which a restart should reset, not carry over from the previous
        # process (same reasoning as crossposting's SyncJob.last_run).
        self.last_run: CalendarLastRun | None = None
        # A short history for the settings page's "Letzte Läufe" — oldest
        # dropped once full, `last_run` is always the same object as `runs[-1]`.
        self.runs: deque[CalendarLastRun] = deque(maxlen=RUN_HISTORY)
        self.streak = Streak()

    async def run(self) -> None:
        async with self.lock:
            error = None
            report = None
            try:
                report = await self.sync.run()
            except Exception as exc:  # noqa: BLE001 - scheduler job must never crash the loop
                logger.exception("calendar sync failed")
                error = str(exc)
            else:
                logger.info("calendar sync complete: %s", report)
            run = CalendarLastRun(at=datetime.now(UTC), error=error, report=report)
            self.last_run = run
            self.runs.append(run)
            self.streak = self.streak.record(error is None)
