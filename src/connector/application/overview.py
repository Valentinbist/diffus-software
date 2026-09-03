"""Use case: assemble the data needed to render the UI's overview page."""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.entities import Delivery, Post, Token
from connector.domain.ports import (
    DeliveryRepository,
    PostRepository,
    PreviewRepository,
    TokenRepository,
)


@dataclass
class PostView:
    post: Post
    deliveries: list[Delivery]
    # Media indexes the connector holds a stored still image for.
    stored_previews: frozenset[int] = frozenset()


@dataclass
class Overview:
    token: Token | None
    posts: list[PostView]


@dataclass
class GetOverview:
    tokens: TokenRepository
    posts: PostRepository
    deliveries: DeliveryRepository
    previews: PreviewRepository

    async def run(self, limit: int = 20) -> Overview:
        token = await self.tokens.get()
        posts = await self.posts.list_recent(limit=limit)
        ids = [p.id for p in posts]
        deliveries_by_post = await self.deliveries.for_posts(ids)
        previews_by_post = await self.previews.stored(ids)
        views = [
            PostView(
                post=post,
                deliveries=deliveries_by_post.get(post.id, []),
                stored_previews=previews_by_post.get(post.id, frozenset()),
            )
            for post in posts
        ]
        return Overview(token=token, posts=views)
