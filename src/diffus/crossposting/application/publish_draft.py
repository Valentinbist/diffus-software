"""Use case: publish a draft — to Instagram, to Telegram, or both.

The core invariant mirrors the poller's own: when Instagram is chosen, the
post is published there first and stored under *Instagram's own media id*
before any Telegram delivery happens — the same id and shape the regular
poller (`SyncPosts`) would see if it polled a moment later. That gives three
separate, independent guarantees against a duplicate Telegram send if the
poller runs concurrently, or this call is retried:

- `posts.upsert` is on-conflict-do-nothing, so the poller inserting the same
  post again is a no-op.
- Every preview index this call would have downloaded is already stored
  here, so the poller's own preview download finds nothing missing.
- `DeliveryRepository.claim` returns None for a row that is already SENT or
  SKIPPED, so the poller's own claim for the same (post, destination) is
  refused outright.

`lock` (the crossposting `SyncJob`'s own lock, handed in by the composition
root) closes the one window those three don't: the moments between
Instagram's `media_publish` call returning and this use case's own
`posts.upsert` and delivery rows landing, during which the poller could
otherwise discover the brand-new Instagram post through `fetch_recent` and
race to deliver it to Telegram itself.

Freigabe: a DRAFT publishes immediately (targets given by the caller, e.g.
SubmitDraft's all-auto path); a REVIEW draft reaches this use case only
through ApproveDraft, with the targets a human just confirmed; a FAILED
draft may be retried, either with fresh targets or (targets=None) with
whatever it stored on its last attempt (`draft.targets`) — `_check` accepts
all three statuses and refuses everything else. Both paths store the
resulting post under `source="diffus"`: a wizard post keeps its App origin
even when it happens to carry Instagram's own media id (see
docs/architecture.md, "Wizard posts published to Instagram"). The Instagram
leg also records a SENT `Delivery` to the fixed `INSTAGRAM_CHANNEL`, so the
overview can show "Instagram ✓" for a wizard post the same way it shows a
Telegram delivery. After storing, a draft started from an event
(`event_ref` = "calendar:<id>") is linked back to that event — best effort:
a failure there is logged, never fatal, because the post itself already
published successfully.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.draft_media import DraftMediaGateway
from diffus.crossposting.application.overview import NoEvents
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    Delivery,
    Destination,
    DraftStatus,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    Preview,
    PublishTargets,
    Token,
)
from diffus.crossposting.domain.errors import DraftError, NotConnectedError
from diffus.crossposting.domain.ports import (
    EventDirectory,
    MediaPublisher,
    PostSink,
    UnitOfWorkFactory,
)

logger = logging.getLogger(__name__)


@dataclass
class PublishDraft:
    uow: UnitOfWorkFactory
    publisher: MediaPublisher
    sinks: Mapping[str, PostSink]
    destinations: Sequence[Destination]
    public_base_url: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731
    events: EventDirectory = field(default_factory=NoEvents)

    async def run(self, draft_id: str, targets: PublishTargets | None = None) -> Post:
        async with self.lock:
            async with self.uow() as uow:
                draft = await uow.drafts.get(draft_id)
                token = await uow.tokens.get(self.publisher.source)

            resolved = targets if targets is not None else (draft.targets if draft else None)
            self._check(draft, token, resolved)
            assert draft is not None  # narrowed by _check, spelled out for the type checker
            assert resolved is not None  # narrowed by _check
            draft.targets = resolved

            if resolved.instagram:
                assert token is not None  # narrowed by _check
                post = await self._publish_to_instagram(draft, token)
            else:
                post = self._telegram_only_post(draft)

            await self._store(draft, post, resolved)
            await self._deliver(draft, post, resolved)
            await self._link_event(draft, post)
            return post

    def _check(
        self, draft: PostDraft | None, token: Token | None, targets: PublishTargets | None
    ) -> None:
        if draft is None:
            raise DraftError("Entwurf nicht gefunden.")
        if draft.status not in (DraftStatus.DRAFT, DraftStatus.REVIEW, DraftStatus.FAILED):
            raise DraftError("Dieser Entwurf wurde schon veröffentlicht.")
        if targets is None or (not targets.instagram and not targets.destinations):
            raise DraftError("Mindestens ein Ziel auswählen.")
        if not set(targets.destinations) <= set(self.destinations):
            raise DraftError("Unbekanntes Ziel.")
        if targets.instagram:
            if token is None:
                raise NotConnectedError("Instagram ist nicht verbunden.")
            if not token.can_publish:
                raise DraftError("Instagram neu verbinden, um Veröffentlichen freizuschalten.")
            if not self.public_base_url.startswith("https://"):
                raise DraftError(
                    "PUBLIC_BASE_URL muss eine öffentliche https-Adresse sein, "
                    "damit Instagram die Bilder laden kann."
                )

    async def _publish_to_instagram(self, draft: PostDraft, token: Token) -> Post:
        urls = [
            draft.public_media_url(self.public_base_url, i) for i in range(len(draft.images))
        ]
        try:
            media_id = await self.publisher.publish_images(token, urls, draft.caption)
            post = await self.publisher.fetch_post(token, media_id)
            # Instagram's own media id, but "diffus" as the source — see the
            # module docstring.
            return dataclasses.replace(post, source="diffus")
        except Exception as exc:
            # Broad on purpose: whatever went wrong (container creation, the
            # readiness poll, media_publish, or reading the post back), the
            # draft must end up FAILED with that reason before the exception
            # keeps propagating to the caller (which shows it to the user).
            draft.mark_failed(str(exc))
            async with self.uow() as uow:
                await uow.drafts.update(draft)
                await uow.commit()
            raise

    def _telegram_only_post(self, draft: PostDraft) -> Post:
        # No Instagram id to key this post on: "diffus:<draft id>" is this
        # app's own post-id namespace, mirroring how every other source
        # prefixes its ids (see docs/architecture.md, "Post id rule").
        base = self.public_base_url
        return Post(
            id=f"diffus:{draft.id}",
            source="diffus",
            caption=draft.caption,
            permalink="",
            media=tuple(
                MediaItem(
                    url=draft.public_media_url(base, i)
                    if base
                    else f"/drafts/{draft.id}/media/{i}",
                    type=MediaType.IMAGE,
                )
                for i in range(len(draft.images))
            ),
            posted_at=self.clock(),
        )

    async def _store(self, draft: PostDraft, post: Post, targets: PublishTargets) -> None:
        async with self.uow() as uow:
            await uow.posts.upsert(post)
            for i, image in enumerate(draft.images):
                await uow.previews.save(
                    Preview(
                        post_id=post.id,
                        index=i,
                        content_type=image.content_type,
                        data=image.data,
                    )
                )
            if targets.instagram:
                instagram_delivery = Delivery(post_id=post.id, destination=INSTAGRAM_CHANNEL)
                instagram_delivery.record_sent(self.clock())
                await uow.deliveries.save(instagram_delivery)
            draft.targets = targets
            draft.mark_published(post.id, self.clock())
            await uow.drafts.update(draft)
            await uow.commit()

    async def _deliver(self, draft: PostDraft, post: Post, targets: PublishTargets) -> None:
        deliver = DeliverPost(media=DraftMediaGateway(draft=draft), sinks=self.sinks, uow=self.uow)
        for destination in self.destinations:
            async with self.uow() as uow:
                delivery = await uow.deliveries.claim(post.id, destination)
                await uow.commit()
            if delivery is None:
                continue

            if destination in targets.destinations:
                await deliver.run(post, delivery)
            else:
                delivery.skip()
                async with self.uow() as uow:
                    await uow.deliveries.save(delivery)
                    await uow.commit()

    async def _link_event(self, draft: PostDraft, post: Post) -> None:
        if draft.event_ref is None or not draft.event_ref.startswith("calendar:"):
            return
        event_id = draft.event_ref.removeprefix("calendar:")
        try:
            await self.events.link(event_id, post.id)
        except Exception:  # noqa: BLE001 - the post already published; linking is best effort
            logger.exception("failed to link post %s back to event %s", post.id, event_id)
