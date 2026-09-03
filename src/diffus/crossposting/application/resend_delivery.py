"""Use case: manually re-send a single (post, chat) delivery from the UI.

Deliberately bypasses the retry cap: a manual resend is a human decision to
try again regardless of how many automatic attempts already failed, so it
does not go through DeliveryRepository.claim().
"""

from __future__ import annotations

from dataclasses import dataclass

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.domain.entities import Delivery, DeliveryStatus, Destination
from diffus.crossposting.domain.errors import ConnectorError
from diffus.crossposting.domain.ports import UnitOfWorkFactory


@dataclass
class ResendDelivery:
    uow: UnitOfWorkFactory
    deliver: DeliverPost

    async def run(self, post_id: str, destination: Destination) -> DeliveryStatus:
        async with self.uow() as uow:
            post = await uow.posts.get(post_id)
            if post is None:
                raise ConnectorError(f"unknown post: {post_id}")
            existing = await uow.deliveries.for_posts([post_id])

        # Reuse the existing row (keeps `attempts`) if there is one for this destination.
        matches = [d for d in existing.get(post_id, []) if d.destination == destination]
        delivery = (
            matches[0] if matches else Delivery(post_id=post_id, destination=destination)
        )

        return await self.deliver.run(post, delivery)
