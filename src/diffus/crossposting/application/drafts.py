"""Use cases: create, read, submit for review/publish, and discard a post draft.

Splitting "create the draft" (CreateDraft) from "publish it" (PublishDraft,
via SubmitDraft/ApproveDraft) mirrors the wizard itself: uploading images is
one request, choosing targets and publishing is the next, and a draft is
what survives between them.

Freigabe: SubmitDraft is the wizard's targets step. When every chosen
channel is auto-publish, it hands straight off to PublishDraft, the same as
before this round, and logs the result AUTO in `review_log`; otherwise it
queues the draft for a human (`PostDraft.submit_for_review`) instead of
publishing. ApproveDraft is what that human's "Freigeben" click calls — a
thin wrapper over PublishDraft, since approving *is* publishing with the
(possibly edited) targets, plus its own APPROVED log entry. RejectDraft is
the Freigabe page's "Ablehnen": unlike DiscardDraft (still the wizard's own
"Verwerfen", which stays silent — a draft not yet submitted never reached
the queue in the first place), it only acts on a reviewable draft and logs
REJECTED before deleting it.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from diffus.crossposting.application.channels import all_auto
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.domain.entities import (
    Destination,
    DraftImage,
    DraftStatus,
    Post,
    PostDraft,
    PublishTargets,
    ReviewLogEntry,
    ReviewOutcome,
)
from diffus.crossposting.domain.errors import DraftError, InvalidImageError, UploadTooLargeError
from diffus.crossposting.domain.ports import ImageProcessor, UnitOfWorkFactory


async def _log_draft_outcome(
    uow: UnitOfWorkFactory,
    draft_id: str,
    outcome: ReviewOutcome,
    targets: PublishTargets,
    post: Post,
) -> None:
    """Shared by SubmitDraft's all-auto path and ApproveDraft: one APPROVED/AUTO log entry,
    in a fresh unit of work after publishing has already committed its own."""
    async with uow() as u:
        draft = await u.drafts.get(draft_id)
        caption = draft.caption if draft is not None else None
        queued_at = draft.submitted_at if draft is not None else None
        await u.review_log.add(
            ReviewLogEntry.new(
                "draft",
                outcome,
                caption,
                targets.as_destinations(),
                datetime.now(UTC),
                post.id,
                queued_at=queued_at,
            )
        )
        await u.commit()


@dataclass
class CreateDraft:
    uow: UnitOfWorkFactory
    images: ImageProcessor

    MAX_IMAGES: ClassVar[int] = PostDraft.MAX_IMAGES
    MAX_TOTAL_BYTES: ClassVar[int] = 20 * 1024 * 1024
    MAX_CAPTION: ClassVar[int] = 2200

    async def run(
        self,
        caption: str,
        uploads: Sequence[tuple[str, bytes]],
        now: datetime | None = None,
        event_ref: str | None = None,
    ) -> PostDraft:
        if not uploads:
            raise InvalidImageError("Mindestens ein Bild ist nötig.")
        if len(uploads) > self.MAX_IMAGES:
            raise UploadTooLargeError("Höchstens 10 Bilder pro Post.")
        if sum(len(data) for _, data in uploads) > self.MAX_TOTAL_BYTES:
            raise UploadTooLargeError("Bilder dürfen zusammen höchstens 20 MB groß sein.")
        if len(caption) > self.MAX_CAPTION:
            raise DraftError("Der Text darf höchstens 2200 Zeichen haben.")

        # normalise() is CPU-bound (Pillow decode/crop/encode); off the event
        # loop so one big upload doesn't stall every other request.
        normalised = [
            await asyncio.to_thread(self.images.normalise, data) for _, data in uploads
        ]

        draft = PostDraft.new(
            caption=caption,
            images=normalised,
            now=now or datetime.now(UTC),
            event_ref=event_ref,
        )
        async with self.uow() as uow:
            await uow.drafts.add(draft)
            await uow.commit()
        return draft


@dataclass
class GetDraft:
    uow: UnitOfWorkFactory

    async def run(self, draft_id: str) -> PostDraft | None:
        async with self.uow() as uow:
            return await uow.drafts.get(draft_id)


@dataclass
class DiscardDraft:
    uow: UnitOfWorkFactory

    async def run(self, draft_id: str) -> None:
        """Deletes an unpublished draft: DRAFT, REVIEW or FAILED. Also the Freigabe "Ablehnen"."""
        async with self.uow() as uow:
            draft = await uow.drafts.get(draft_id)
            if draft is not None and draft.status in (
                DraftStatus.DRAFT,
                DraftStatus.REVIEW,
                DraftStatus.FAILED,
            ):
                await uow.drafts.delete(draft_id)
                await uow.commit()


@dataclass
class GetDraftImage:
    uow: UnitOfWorkFactory

    async def run(self, draft_id: str, index: int, key: str | None = None) -> DraftImage | None:
        """`key`, when given, must match the draft's public_key (constant-time) or this is None."""
        async with self.uow() as uow:
            if key is not None:
                stored_key = await uow.drafts.public_key(draft_id)
                if stored_key is None or not secrets.compare_digest(stored_key, key):
                    return None
            return await uow.drafts.get_image(draft_id, index)


@dataclass
class SubmitResult:
    post: Post | None
    queued: bool


@dataclass
class SubmitDraft:
    """The wizard's targets step: publish immediately, or queue for Freigabe."""

    uow: UnitOfWorkFactory
    publish: PublishDraft
    destinations: Sequence[Destination]

    async def run(self, draft_id: str, targets: PublishTargets) -> SubmitResult:
        async with self.uow() as uow:
            draft = await uow.drafts.get(draft_id)
            auto = await uow.channels.get_all()

        if draft is None:
            raise DraftError("Entwurf nicht gefunden.")
        if draft.status != DraftStatus.DRAFT:
            raise DraftError("Dieser Entwurf wurde schon veröffentlicht.")
        if not targets.instagram and not targets.destinations:
            raise DraftError("Mindestens ein Ziel auswählen.")
        if not set(targets.destinations) <= set(self.destinations):
            raise DraftError("Unbekanntes Ziel.")

        if all_auto(auto, targets):
            post = await self.publish.run(draft_id, targets)
            await _log_draft_outcome(self.uow, draft_id, ReviewOutcome.AUTO, targets, post)
            return SubmitResult(post=post, queued=False)

        draft.submit_for_review(targets, datetime.now(UTC))
        async with self.uow() as uow:
            await uow.drafts.update(draft)
            await uow.commit()
        return SubmitResult(post=None, queued=True)


@dataclass
class ApproveDraft:
    """The Freigabe page's "Freigeben": publish a queued (or retried) draft with its targets."""

    publish: PublishDraft
    uow: UnitOfWorkFactory

    async def run(self, draft_id: str, targets: PublishTargets) -> Post:
        post = await self.publish.run(draft_id, targets)
        await _log_draft_outcome(self.uow, draft_id, ReviewOutcome.APPROVED, targets, post)
        return post


@dataclass
class RejectDraft:
    """The Freigabe page's "Ablehnen": logs REJECTED, then deletes — a no-op for a non-reviewable
    or missing draft (a second click, or a draft that never reached the queue)."""

    uow: UnitOfWorkFactory

    async def run(self, draft_id: str) -> None:
        async with self.uow() as uow:
            draft = await uow.drafts.get(draft_id)
            if draft is None or not draft.is_reviewable():
                return
            await uow.review_log.add(
                ReviewLogEntry.new(
                    "draft",
                    ReviewOutcome.REJECTED,
                    draft.caption,
                    (),
                    datetime.now(UTC),
                    queued_at=draft.submitted_at,
                )
            )
            await uow.drafts.delete(draft_id)
            await uow.commit()
