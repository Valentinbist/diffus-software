"""Use case: the index page's activity heatmap and "Post Nummer N" milestone line."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from diffus.crossposting.domain.ports import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class Activity:
    total: int  # every post the connector knows (posts.count())
    posted_at: tuple[datetime, ...]  # posts.posted_at_since(since)


@dataclass
class GetActivity:
    uow: UnitOfWorkFactory

    async def run(self, since: datetime) -> Activity:
        async with self.uow() as uow:
            total = await uow.posts.count()
            posted_at = await uow.posts.posted_at_since(since)
        return Activity(total=total, posted_at=tuple(posted_at))
