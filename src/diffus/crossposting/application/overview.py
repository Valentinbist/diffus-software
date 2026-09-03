"""Use case: assemble the data needed to render the UI's overview page."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from diffus.crossposting.domain.entities import Delivery, LinkedEvent, Post, Token
from diffus.crossposting.domain.ports import EventDirectory, UnitOfWorkFactory


@dataclass
class PostView:
    post: Post
    deliveries: list[Delivery]
    # Media indexes the connector holds a stored still image for.
    stored_previews: frozenset[int] = frozenset()
    events: list[LinkedEvent] = field(default_factory=list)


@dataclass
class Overview:
    token: Token | None
    posts: list[PostView]


@dataclass
class NoEvents:
    """EventDirectory used when the calendar context is off: nothing is linked."""

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[LinkedEvent]]:
        return {}


@dataclass
class GetOverview:
    uow: UnitOfWorkFactory
    source: str
    events: EventDirectory = field(default_factory=NoEvents)

    async def run(self, limit: int = 20) -> Overview:
        async with self.uow() as uow:
            token = await uow.tokens.get(self.source)
            posts = await uow.posts.list_recent(limit=limit)
            ids = [p.id for p in posts]
            deliveries_by_post = await uow.deliveries.for_posts(ids)
            previews_by_post = await uow.previews.stored(ids)
        events_by_post = await self.events.for_posts(ids)
        views = [
            PostView(
                post=post,
                deliveries=deliveries_by_post.get(post.id, []),
                stored_previews=previews_by_post.get(post.id, frozenset()),
                events=events_by_post.get(post.id, []),
            )
            for post in posts
        ]
        return Overview(token=token, posts=views)
