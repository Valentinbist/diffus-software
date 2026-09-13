"""The periodic job: refresh the Instagram token, then sync posts.

Refresh is welded to sync on purpose. It used to be a separate 24h APScheduler
job, and since an interval trigger first fires one full interval after process
start, a host that restarted more often than daily never ran it at all — the
long-lived token then expired silently at day 60. Anything that keeps the token
alive has to run on a cadence shorter than the process lifetime, and sync is
the only such cadence we have.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from diffus.crossposting.application.refresh_token import EnsureFreshToken
from diffus.crossposting.application.sync_posts import SyncPosts, SyncReport
from diffus.crossposting.domain.errors import NotConnectedError
from diffus.shared.automation import RUN_HISTORY, Streak

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LastRun:
    """What the UI shows about one run. A None error means that step went through."""

    at: datetime
    sync_error: str | None = None
    refresh_error: str | None = None
    # The report `_sync` got back on success; None on error (nothing to summarise).
    report: SyncReport | None = None


class SyncJob:
    """Serialises refresh+sync so the scheduler and the UI can't overlap."""

    def __init__(self, sync: SyncPosts, refresh: EnsureFreshToken) -> None:
        self.sync = sync
        self.refresh = refresh
        self.lock = asyncio.Lock()
        # In-memory on purpose: it answers "is the poller alive?", which a
        # restart should reset, not carry over from the previous process.
        self.last_run: LastRun | None = None
        # A short history for the settings page's "Letzte Läufe" — oldest
        # dropped once full, `last_run` is always the same object as `runs[-1]`.
        self.runs: deque[LastRun] = deque(maxlen=RUN_HISTORY)
        self.streak = Streak()

    async def run(self) -> None:
        async with self.lock:
            refresh_error = await self._refresh()
            try:
                report, sync_error = await self._sync()
            except NotConnectedError:
                logger.info("Instagram not connected, skipping sync")
                return
            run = LastRun(
                at=datetime.now(UTC),
                sync_error=sync_error,
                refresh_error=refresh_error,
                report=report,
            )
            self.last_run = run
            self.runs.append(run)
            self.streak = self.streak.record(sync_error is None and refresh_error is None)

    async def _refresh(self) -> str | None:
        try:
            await self.refresh.run()
        except Exception as exc:  # noqa: BLE001 - a stale token still beats skipping the sync
            logger.exception("token refresh FAILED - manual intervention required")
            return str(exc)
        return None

    async def _sync(self) -> tuple[SyncReport | None, str | None]:
        """Returns (report, failure). NotConnectedError propagates: no connection, no run."""
        try:
            report = await self.sync.run()
        except NotConnectedError:
            raise
        except Exception as exc:  # noqa: BLE001 - scheduler job must never crash the loop
            logger.exception("sync job failed")
            return None, str(exc)
        logger.info("sync complete: %s", report)
        return report, None
