"""Scheduler bootstrap shared by every bounded context that needs a background job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler


def start_scheduler(job: Callable[[], Awaitable[None]], minutes: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(job, "interval", minutes=minutes)
    scheduler.start()
    return scheduler
