"""Use case: deliver one post to one destination, and record the outcome.

Shared by SyncPosts (after a freshly claimed delivery) and ResendDelivery (a
manual resend from the UI). Owns the two transaction boundaries around a
network delivery: the caller commits the claim, DeliverPost delivers over
the network, then this saves the result and commits.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from diffus.crossposting.domain.entities import Delivery, DeliveryStatus, Post
from diffus.crossposting.domain.ports import MediaGateway, PostSink, UnitOfWorkFactory

logger = logging.getLogger(__name__)


@dataclass
class DeliverPost:
    media: MediaGateway
    sinks: Mapping[str, PostSink]
    uow: UnitOfWorkFactory

    async def run(self, post: Post, delivery: Delivery) -> DeliveryStatus:
        sink = self.sinks.get(delivery.destination.sink)
        if sink is None:
            logger.error("no sink configured for %r", delivery.destination.sink)
            delivery.record_failure(f"no sink configured for {delivery.destination.sink!r}")
        else:
            try:
                async with self.media.fetch(post) as media:
                    await sink.deliver(post, delivery.destination.address, media)
                delivery.record_sent(datetime.now(UTC))
            except Exception as exc:  # noqa: BLE001 - a failed delivery must never abort the caller
                logger.exception(
                    "failed to deliver post %s to %s", post.id, delivery.destination
                )
                delivery.record_failure(str(exc))

        async with self.uow() as uow:
            await uow.deliveries.save(delivery)
            await uow.commit()
        return delivery.status
