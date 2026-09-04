"""Use cases: create, read and discard a post draft — the upload half of the publishing wizard.

Splitting "create the draft" from "publish it" (application/publish_draft.py)
mirrors the wizard itself: uploading images is one request, choosing targets
and publishing is the next, and a draft is what survives between them.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from diffus.crossposting.domain.entities import DraftImage, DraftStatus, PostDraft
from diffus.crossposting.domain.errors import DraftError, InvalidImageError, UploadTooLargeError
from diffus.crossposting.domain.ports import ImageProcessor, UnitOfWorkFactory


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

        draft = PostDraft.new(caption=caption, images=normalised, now=now or datetime.now(UTC))
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
        """Deletes a still-unpublished draft. A published/failed/missing draft is left alone."""
        async with self.uow() as uow:
            draft = await uow.drafts.get(draft_id)
            if draft is not None and draft.status == DraftStatus.DRAFT:
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
