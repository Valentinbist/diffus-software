"""Use case: manually re-send a single (post, chat) delivery from the UI."""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.entities import DeliveryStatus
from connector.domain.errors import ConnectorError
from connector.domain.ports import DeliveryRepository, MediaGateway, PostRepository, PostSink


@dataclass
class ResendDelivery:
    posts: PostRepository
    deliveries: DeliveryRepository
    media: MediaGateway
    sink: PostSink

    async def run(self, post_id: str, chat_id: str) -> DeliveryStatus:
        post = await self.posts.get(post_id)
        if post is None:
            raise ConnectorError(f"unknown post: {post_id}")

        try:
            async with self.media.fetch(post) as media_paths:
                await self.sink.deliver(post, chat_id, media_paths)
            await self.deliveries.mark(post_id, chat_id, DeliveryStatus.SENT)
            return DeliveryStatus.SENT
        except Exception as exc:  # noqa: BLE001 - never raise on delivery failure
            await self.deliveries.mark(
                post_id, chat_id, DeliveryStatus.FAILED, error=str(exc)
            )
            return DeliveryStatus.FAILED
