"""Use case: poll the Instagram source and fan-out new posts to configured channels.

A fresh delivery to a channel whose auto-publish switch is off queues for
Freigabe instead of sending (Delivery.queue_for_review) — see
docs/architecture.md and channels.py. A FAILED delivery being retried always
delivers regardless of the switch: the switch is consulted once, at first
sight of a (post, destination) pair, not on every retry.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.domain.entities import DeliveryStatus, Destination, Post, Preview
from diffus.crossposting.domain.errors import NotConnectedError
from diffus.crossposting.domain.ports import MediaGateway, PostSource, UnitOfWorkFactory

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    fetched: int = 0
    new: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    queued: int = 0
    previews: int = 0


@dataclass
class SyncPosts:
    source: PostSource
    media: MediaGateway
    deliver: DeliverPost
    destinations: Sequence[Destination]
    uow: UnitOfWorkFactory

    async def run(self, mark_seen_only: bool = False) -> SyncReport:
        report = SyncReport()

        async with self.uow() as uow:
            if await uow.posts.count() == 0:
                logger.info("posts table is empty; forcing mark_seen_only for this run")
                mark_seen_only = True
            token = await uow.tokens.get(self.source.source)
            auto = await uow.channels.get_all()
        if token is None:
            raise NotConnectedError("Instagram is not connected")

        fetched_posts = await self.source.fetch_recent(token)
        report.fetched = len(fetched_posts)

        async with self.uow() as uow:
            stored_previews = await uow.previews.stored([p.id for p in fetched_posts])

        for post in fetched_posts:
            downloaded = await self._download_previews(
                post, stored_previews.get(post.id, frozenset())
            )

            async with self.uow() as uow:
                existing = await uow.posts.get(post.id)
                if existing is None:
                    report.new += 1
                await uow.posts.upsert(post)
                for preview in downloaded:
                    await uow.previews.save(preview)
                await uow.commit()
            report.previews += len(downloaded)

            for destination in self.destinations:
                async with self.uow() as uow:
                    delivery = await uow.deliveries.claim(post.id, destination)
                    await uow.commit()
                if delivery is None:
                    continue

                if mark_seen_only:
                    delivery.skip()
                    async with self.uow() as uow:
                        await uow.deliveries.save(delivery)
                        await uow.commit()
                    report.skipped += 1
                    continue

                # Only a fresh claim (never attempted before) consults the
                # switch; a FAILED retry always delivers — the switch decided
                # once, when the delivery was first created, not on every
                # retry (§6a).
                if delivery.status == DeliveryStatus.PENDING and not auto.get(destination, False):
                    delivery.queue_for_review()
                    async with self.uow() as uow:
                        await uow.deliveries.save(delivery)
                        await uow.commit()
                    report.queued += 1
                    continue

                status = await self.deliver.run(post, delivery)
                if status == DeliveryStatus.SENT:
                    report.sent += 1
                else:
                    report.failed += 1

        return report

    async def _download_previews(self, post: Post, have: frozenset[int]) -> list[Preview]:
        """Download each media item's still image while the CDN link is fresh. Best effort.

        Every poll returns fresh links for the recent posts, so anything missed
        here is simply retried on the next run.
        """
        downloaded: list[Preview] = []
        for index, item in enumerate(post.media):
            if index in have or item.preview_url is None:
                continue
            try:
                image = await self.media.download_image(item.preview_url)
            except Exception:  # noqa: BLE001 - a missing preview must never block a delivery
                logger.exception("failed to download preview %s of post %s", index, post.id)
                continue
            if image is None:
                continue
            content_type, data = image
            downloaded.append(
                Preview(post_id=post.id, index=index, content_type=content_type, data=data)
            )
        return downloaded
