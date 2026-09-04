"""Use cases: the Freigabe queue — drafts and polled-post deliveries waiting on a human.

Two kinds of thing queue for approval, and they are approved differently
(see the Decisions table in the round 3 plan): a wizard draft's whole set of
targets is approved together (ApproveDraft, in drafts.py, over
PublishDraft) — nothing here owns that. A polled post's REVIEW deliveries
are approved per destination (ApprovePostDeliveries) since a post can have
several channels queued independently (e.g. one auto Telegram chat already
sent, another chat and Instagram still waiting). GetReviewQueue assembles
both halves for the /freigabe page; CountReview is the same query, counted,
for the nav badge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.overview import PostView
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.domain.entities import ComposeHint, DeliveryStatus, Destination, PostDraft
from diffus.crossposting.domain.errors import ConnectorError
from diffus.crossposting.domain.ports import EventDirectory, UnitOfWorkFactory


@dataclass
class DraftReview:
    draft: PostDraft
    image_urls: tuple[str, ...]
    hint: ComposeHint | None


@dataclass
class PostReview:
    view: PostView
    # The channels this post's REVIEW rows propose, intersected with what is
    # currently configured — a chat removed from TELEGRAM_CHAT_IDS since the
    # row was queued must not be offered as a checkbox.
    proposed: list[Destination]


@dataclass
class ReviewQueue:
    drafts: list[DraftReview]
    posts: list[PostReview]


@dataclass
class GetReviewQueue:
    uow: UnitOfWorkFactory
    detail: GetPostDetail
    events: EventDirectory
    destinations: Sequence[Destination]

    async def run(self) -> ReviewQueue:
        async with self.uow() as uow:
            drafts = await uow.drafts.in_review()
            in_review = await uow.deliveries.in_review()

        draft_reviews = []
        for draft in drafts:
            hint = None
            if draft.event_ref is not None and draft.event_ref.startswith("calendar:"):
                hint = await self.events.compose_hint(draft.event_ref.removeprefix("calendar:"))
            image_urls = tuple(f"/drafts/{draft.id}/media/{i}" for i in range(len(draft.images)))
            draft_reviews.append(DraftReview(draft=draft, image_urls=image_urls, hint=hint))

        post_reviews = []
        for post_id, rows in in_review.items():
            view = await self.detail.run(post_id)
            if view is None:
                continue
            proposed = [row.destination for row in rows if row.destination in self.destinations]
            post_reviews.append(PostReview(view=view, proposed=proposed))

        return ReviewQueue(drafts=draft_reviews, posts=post_reviews)


@dataclass
class CountReview:
    uow: UnitOfWorkFactory

    async def run(self) -> int:
        async with self.uow() as uow:
            drafts = await uow.drafts.count_in_review()
            posts = await uow.deliveries.count_posts_in_review()
        return drafts + posts


@dataclass
class ApprovePostDeliveries:
    """Approves a subset of one post's REVIEW deliveries; the rest are rejected.

    `lock` (handed in as the crossposting SyncJob's own lock, like
    PublishDraft's) makes a double-click safe: the flip from REVIEW to
    PENDING/SKIPPED happens under it, in one committed unit of work, so a
    second concurrent call finds no REVIEW rows left to act on.
    """

    uow: UnitOfWorkFactory
    deliver: DeliverPost
    destinations: Sequence[Destination]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def run(self, post_id: str, chosen: Sequence[Destination]) -> list[DeliveryStatus]:
        configured = set(self.destinations)
        async with self.lock:
            async with self.uow() as uow:
                post = await uow.posts.get(post_id)
                if post is None:
                    raise ConnectorError("Unbekannter Post.")
                in_review = await uow.deliveries.in_review()
                rows = in_review.get(post_id, [])

                to_send = []
                for row in rows:
                    if row.destination in chosen and row.destination in configured:
                        row.approve()
                        to_send.append(row)
                    else:
                        row.reject()
                    await uow.deliveries.save(row)
                await uow.commit()

            # Delivering is a network call: it happens after the unit of work
            # above is closed, the same rule every other use case here follows.
            return [await self.deliver.run(post, row) for row in to_send]


@dataclass
class RejectPostDeliveries:
    uow: UnitOfWorkFactory

    async def run(self, post_id: str) -> None:
        async with self.uow() as uow:
            in_review = await uow.deliveries.in_review()
            for row in in_review.get(post_id, []):
                row.reject()
                await uow.deliveries.save(row)
            await uow.commit()
