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
from dataclasses import dataclass
from datetime import UTC, datetime

from connector.application.refresh_token import EnsureFreshToken
from connector.application.sync_posts import SyncPosts
from connector.domain.errors import NotConnectedError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LastRun:
    """What the UI shows about the most recent run. A None error means that step went through."""

    at: datetime
    sync_error: str | None = None
    refresh_error: str | None = None


class SyncJob:
    """Serialises refresh+sync so the scheduler and the UI can't overlap."""

    def __init__(self, sync: SyncPosts, refresh: EnsureFreshToken) -> None:
        self.sync = sync
        self.refresh = refresh
        self.lock = asyncio.Lock()
        # In-memory on purpose: it answers "is the poller alive?", which a
        # restart should reset, not carry over from the previous process.
        self.last_run: LastRun | None = None

    async def run(self) -> None:
        async with self.lock:
            refresh_error = await self._refresh()
            try:
                sync_error = await self._sync()
            except NotConnectedError:
                logger.info("Instagram not connected, skipping sync")
                return
            self.last_run = LastRun(
                at=datetime.now(UTC), sync_error=sync_error, refresh_error=refresh_error
            )

    async def _refresh(self) -> str | None:
        try:
            await self.refresh.run()
        except Exception as exc:  # noqa: BLE001 - a stale token still beats skipping the sync
            logger.exception("token refresh FAILED - manual intervention required")
            return str(exc)
        return None

    async def _sync(self) -> str | None:
        """Returns the failure, if any. NotConnectedError propagates: no connection, no run."""
        try:
            report = await self.sync.run()
        except NotConnectedError:
            raise
        except Exception as exc:  # noqa: BLE001 - scheduler job must never crash the loop
            logger.exception("sync job failed")
            return str(exc)
        logger.info("sync complete: %s", report)
        return None
