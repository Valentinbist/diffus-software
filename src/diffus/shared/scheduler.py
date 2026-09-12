"""Scheduler bootstrap shared by every bounded context that needs a background job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler


def start_scheduler(job: Callable[[], Awaitable[None]], minutes: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(job, "interval", minutes=minutes)
    scheduler.start()
    return scheduler


def next_run_time(scheduler: AsyncIOScheduler) -> datetime | None:
    """The one interval job's next fire time (aware UTC), or None before the scheduler starts."""
    jobs = scheduler.get_jobs()
    return jobs[0].next_run_time if jobs else None
