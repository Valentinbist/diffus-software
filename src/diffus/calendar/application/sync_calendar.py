"""Use case: sync the shared external calendar into local storage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from diffus.calendar.domain.ports import CalendarGateway, CalendarUnitOfWorkFactory

logger = logging.getLogger(__name__)


@dataclass
class CalendarSyncReport:
    sub_calendars: int = 0
    fetched: int = 0
    removed: int = 0


@dataclass
class SyncCalendar:
    calendar: CalendarGateway
    uow: CalendarUnitOfWorkFactory
    past_months: int = 3
    future_months: int = 6

    async def run(self, now: datetime | None = None) -> CalendarSyncReport:
        now = now or datetime.now(UTC)
        today = now.date()
        start = _month_start(today, -self.past_months)
        end = _month_start(today, self.future_months + 1) - timedelta(days=1)

        snapshot = await self.calendar.fetch(start, end)  # network, outside any unit of work

        report = CalendarSyncReport(
            sub_calendars=len(snapshot.sub_calendars), fetched=len(snapshot.events)
        )
        async with self.uow() as uow:
            await uow.sub_calendars.save_all(snapshot.sub_calendars)
            await uow.events.upsert_many(snapshot.events)
            if snapshot.events:
                # The window is shrunk by a day at each edge so the API's own
                # inclusivity of startDate/endDate can never cause a false
                # removal right at the boundary.
                report.removed = await uow.events.mark_removed(
                    window_start=_utc_midnight(start + timedelta(days=1)),
                    window_end=_utc_midnight(end),
                    seen_ids=[event.id for event in snapshot.events],
                    at=now,
                )
            else:
                # An empty answer is far more likely a hiccup (network blip,
                # upstream outage) than the calendar genuinely being wiped;
                # mark nothing rather than remove every stored event.
                logger.warning(
                    "kalender.digital returned no events for %s..%s; treating as a "
                    "hiccup, marking nothing removed",
                    start,
                    end,
                )
            await uow.commit()
        return report


def _month_start(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)
