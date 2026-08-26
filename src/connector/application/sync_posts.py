"""Use case: poll the Instagram source and fan-out new posts to Telegram chats."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from connector.domain.entities import DeliveryStatus
from connector.domain.ports import (
    DeliveryRepository,
    MediaGateway,
    PostRepository,
    PostSink,
    PostSource,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    fetched: int = 0
    new: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class SyncPosts:
    source: PostSource
    posts: PostRepository
    deliveries: DeliveryRepository
    media: MediaGateway
    sink: PostSink
    chat_ids: Sequence[str]

    async def run(self, mark_seen_only: bool = False) -> SyncReport:
        report = SyncReport()

        if await self.posts.count() == 0:
            logger.info("posts table is empty; forcing mark_seen_only for this run")
            mark_seen_only = True

        fetched_posts = await self.source.fetch_recent()
        report.fetched = len(fetched_posts)

        for post in fetched_posts:
            existing = await self.posts.get(post.id)
            if existing is None:
                report.new += 1
            await self.posts.upsert(post)

            for chat_id in self.chat_ids:
                claimed = await self.deliveries.claim(post.id, chat_id)
                if not claimed:
                    continue

                if mark_seen_only:
                    await self.deliveries.mark(post.id, chat_id, DeliveryStatus.SKIPPED)
                    report.skipped += 1
                    continue

                try:
                    async with self.media.fetch(post) as media_paths:
                        await self.sink.deliver(post, chat_id, media_paths)
                    await self.deliveries.mark(post.id, chat_id, DeliveryStatus.SENT)
                    report.sent += 1
                except Exception as exc:  # noqa: BLE001 - must not abort the sync loop
                    logger.exception(
                        "failed to deliver post %s to chat %s", post.id, chat_id
                    )
                    await self.deliveries.mark(
                        post.id, chat_id, DeliveryStatus.FAILED, error=str(exc)
                    )
                    report.failed += 1

        return report
