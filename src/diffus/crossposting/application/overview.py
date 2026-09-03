"""Use case: assemble the data needed to render the UI's overview page."""

from __future__ import annotations

from dataclasses import dataclass

from diffus.crossposting.domain.entities import Delivery, Post, Token
from diffus.crossposting.domain.ports import UnitOfWorkFactory


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
    uow: UnitOfWorkFactory
    source: str

    async def run(self, limit: int = 20) -> Overview:
        async with self.uow() as uow:
            token = await uow.tokens.get(self.source)
            posts = await uow.posts.list_recent(limit=limit)
            ids = [p.id for p in posts]
            deliveries_by_post = await uow.deliveries.for_posts(ids)
            previews_by_post = await uow.previews.stored(ids)
        views = [
            PostView(
                post=post,
                deliveries=deliveries_by_post.get(post.id, []),
                stored_previews=previews_by_post.get(post.id, frozenset()),
            )
            for post in posts
        ]
        return Overview(token=token, posts=views)
