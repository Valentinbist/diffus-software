"""Adapters implemented over the crossposting context's own use cases.

The one deliberate exception to "contexts never import each other's domain,
application or infrastructure": an adapter under a context's own
`infrastructure/` may call another context's `application/` use cases —
reads *and*, since this round, commands too — because the application layer
of a context is its public API (see docs/architecture.md, Bounded contexts).
`GetOverview` and `GetPostDetail` are that public API for reading posts; the
`DeliveryStatus` import is for the same reason — deciding what "delivered"
means from a raw delivery list is this adapter's mapping job, not
crossposting's. `CrosspostingPublisher` is the command half: it drives
`CreateDraft`/`PublishDraft`/`DiscardDraft`, the application-*command*
exception the owner approved for this round.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.domain.entities import (
    DraftPreview,
    DraftRef,
    InstagramState,
    LinkablePost,
    PublishedPost,
    PublishOptions,
    TelegramTarget,
)
from diffus.calendar.domain.errors import PublishError
from diffus.crossposting.application.drafts import CreateDraft, DiscardDraft, GetDraft
from diffus.crossposting.application.overview import GetOverview, PostView
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.application.publish_readiness import GetPublishReadiness
from diffus.crossposting.domain.entities import DeliveryStatus, Destination, PublishTargets
from diffus.crossposting.domain.errors import ConnectorError


def _to_linkable(view: PostView) -> LinkablePost:
    first = min(view.stored_previews, default=None)
    thumbnail_url = (
        f"/posts/{view.post.id}/media/{first}" if first is not None else view.post.cover_url
    )

    return LinkablePost(
        id=view.post.id,
        caption=view.post.caption,
        permalink=view.post.permalink,
        posted_at=view.post.posted_at,
        thumbnail_url=thumbnail_url,
        detail_url=f"/posts/{view.post.id}",
        delivered=any(d.status == DeliveryStatus.SENT for d in view.deliveries),
    )


@dataclass
class CrosspostingPostCatalog:
    overview: GetOverview
    detail: GetPostDetail

    async def recent(self, limit: int = 50) -> list[LinkablePost]:
        overview = await self.overview.run(limit=limit)
        return [_to_linkable(view) for view in overview.posts]

    async def by_ids(self, ids: Sequence[str]) -> dict[str, LinkablePost]:
        found: dict[str, LinkablePost] = {}
        for post_id in ids:
            view = await self.detail.run(post_id)
            if view is not None:
                found[post_id] = _to_linkable(view)
        return found


@dataclass
class CrosspostingPublisher:
    """PostPublisher implemented over crossposting's drafting/publishing use cases.

    Every ConnectorError the wrapped use cases raise (DraftError,
    NotConnectedError, crossposting's own PublishError, ...) is re-raised as
    the calendar's own PublishError(str(exc)): the calendar's application
    layer and templates depend only on diffus.calendar.domain.errors, never
    on crossposting's.
    """

    create: CreateDraft
    publish_draft: PublishDraft
    readiness: GetPublishReadiness
    drafts: GetDraft
    discard_draft: DiscardDraft
    destinations: Sequence[Destination]

    async def options(self) -> PublishOptions:
        try:
            readiness = await self.readiness.run()
        except ConnectorError as exc:
            raise PublishError(str(exc)) from exc

        if not readiness.connected:
            instagram = InstagramState.NOT_CONNECTED
        elif not readiness.can_publish:
            instagram = InstagramState.NO_PUBLISH_SCOPE
        elif not readiness.public_https:
            instagram = InstagramState.NO_PUBLIC_URL
        else:
            instagram = InstagramState.READY

        single = len(self.destinations) == 1
        targets = tuple(
            TelegramTarget(
                address=d.address, label="Telegram" if single else f"Telegram {d.address}"
            )
            for d in self.destinations
        )
        return PublishOptions(instagram=instagram, targets=targets)

    async def create_draft(
        self, caption: str, uploads: Sequence[tuple[str, bytes]]
    ) -> DraftRef:
        try:
            draft = await self.create.run(caption, uploads)
        except ConnectorError as exc:
            raise PublishError(str(exc)) from exc
        return DraftRef(id=draft.id)

    async def get_draft(self, draft_id: str) -> DraftPreview | None:
        try:
            draft = await self.drafts.run(draft_id)
        except ConnectorError as exc:
            raise PublishError(str(exc)) from exc
        if draft is None:
            return None
        return DraftPreview(
            id=draft.id,
            caption=draft.caption,
            image_urls=tuple(f"/drafts/{draft.id}/media/{i}" for i in range(len(draft.images))),
        )

    async def publish(
        self, draft_id: str, instagram: bool, telegram_addresses: Sequence[str]
    ) -> PublishedPost:
        targets = PublishTargets(
            instagram=instagram,
            destinations=tuple(Destination("telegram", a) for a in telegram_addresses),
        )
        try:
            post = await self.publish_draft.run(draft_id, targets)
        except ConnectorError as exc:
            raise PublishError(str(exc)) from exc
        return PublishedPost(id=post.id, permalink=post.permalink, detail_url=f"/posts/{post.id}")

    async def discard(self, draft_id: str) -> None:
        try:
            await self.discard_draft.run(draft_id)
        except ConnectorError as exc:
            raise PublishError(str(exc)) from exc
