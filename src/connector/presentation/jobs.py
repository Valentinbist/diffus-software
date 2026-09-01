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

from connector.application.refresh_token import EnsureFreshToken
from connector.application.sync_posts import SyncPosts
from connector.domain.errors import NotConnectedError

logger = logging.getLogger(__name__)


class SyncJob:
    """Serialises refresh+sync so the scheduler and the UI can't overlap."""

    def __init__(self, sync: SyncPosts, refresh: EnsureFreshToken) -> None:
        self.sync = sync
        self.refresh = refresh
        self.lock = asyncio.Lock()

    async def run(self) -> None:
        async with self.lock:
            await self._refresh()
            await self._sync()

    async def _refresh(self) -> None:
        try:
            await self.refresh.run()
        except Exception:  # noqa: BLE001 - a stale token still beats skipping the sync
            logger.exception("token refresh FAILED - manual intervention required")

    async def _sync(self) -> None:
        try:
            report = await self.sync.run()
            logger.info("sync complete: %s", report)
        except NotConnectedError:
            logger.info("Instagram not connected, skipping sync")
        except Exception:  # noqa: BLE001 - scheduler job must never crash the loop
            logger.exception("sync job failed")
