"""CalendarSyncJob: swallows sync failures so the scheduler tick survives."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.application.sync_job import CalendarSyncJob
from diffus.calendar.domain.entities import CalendarSnapshot
from tests.calendar.fakes import FailingCalendar, FakeCalendar, FakeCalendarUnitOfWork


def make_job(calendar=None) -> CalendarSyncJob:
    calendar = calendar if calendar is not None else FakeCalendar(CalendarSnapshot((), ()))
    sync = SyncCalendar(calendar=calendar, uow=FakeCalendarUnitOfWork())
    return CalendarSyncJob(sync)


async def test_a_clean_run_records_last_run_with_no_error():
    job = make_job()

    await job.run()

    assert job.last_run is not None
    assert job.last_run.error is None
    assert job.last_run.at > datetime.now(UTC) - timedelta(minutes=1)


async def test_a_failing_sync_records_the_error_and_does_not_raise():
    job = make_job(calendar=FailingCalendar(RuntimeError("kalender.digital is down")))

    await job.run()  # must not raise

    assert job.last_run is not None
    assert job.last_run.error == "kalender.digital is down"


async def test_the_lock_lets_concurrent_runs_complete_without_raising():
    job = make_job()

    await asyncio.gather(job.run(), job.run())

    assert job.last_run is not None
    assert job.last_run.error is None
