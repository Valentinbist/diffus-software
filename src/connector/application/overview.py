"""Use case: assemble the data needed to render the UI's overview page."""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.entities import Delivery, Post, Token
from connector.domain.ports import DeliveryRepository, PostRepository, TokenRepository


@dataclass
class PostView:
    post: Post
    deliveries: list[Delivery]


@dataclass
class Overview:
    token: Token | None
    posts: list[PostView]


@dataclass
class GetOverview:
    tokens: TokenRepository
    posts: PostRepository
    deliveries: DeliveryRepository

    async def run(self, limit: int = 20) -> Overview:
        token = await self.tokens.get()
        posts = await self.posts.list_recent(limit=limit)
        deliveries_by_post = await self.deliveries.for_posts([p.id for p in posts])
        views = [
            PostView(post=post, deliveries=deliveries_by_post.get(post.id, []))
            for post in posts
        ]
        return Overview(token=token, posts=views)
