"""Use case: everything the UI shows about one post — media, caption, per-chat delivery state."""

from __future__ import annotations

from dataclasses import dataclass

from connector.application.overview import PostView
from connector.domain.ports import DeliveryRepository, PostRepository, PreviewRepository


@dataclass
class GetPostDetail:
    posts: PostRepository
    deliveries: DeliveryRepository
    previews: PreviewRepository

    async def run(self, post_id: str) -> PostView | None:
        post = await self.posts.get(post_id)
        if post is None:
            return None
        deliveries = await self.deliveries.for_posts([post_id])
        previews = await self.previews.stored([post_id])
        return PostView(
            post=post,
            deliveries=deliveries.get(post_id, []),
            stored_previews=previews.get(post_id, frozenset()),
        )
