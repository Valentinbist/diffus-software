"""Use case: everything the UI shows about one post — media, caption, per-chat delivery state."""

from __future__ import annotations

from dataclasses import dataclass

from connector.application.overview import PostView
from connector.domain.ports import UnitOfWorkFactory


@dataclass
class GetPostDetail:
    uow: UnitOfWorkFactory

    async def run(self, post_id: str) -> PostView | None:
        async with self.uow() as uow:
            post = await uow.posts.get(post_id)
            if post is None:
                return None
            deliveries = await uow.deliveries.for_posts([post_id])
            previews = await uow.previews.stored([post_id])
        return PostView(
            post=post,
            deliveries=deliveries.get(post_id, []),
            stored_previews=previews.get(post_id, frozenset()),
        )
