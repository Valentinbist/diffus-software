"""MediaGateway that falls back to stored previews when the CDN link has gone stale.

A polled post's REVIEW deliveries can sit for days waiting on a human;
Instagram's CDN links are short-lived (see docs/architecture.md, "Media"),
so by the time someone approves it the original `HttpMediaGateway.fetch`
call may simply fail. `FallbackMediaGateway` wraps a real gateway and, only
on failure, serves the still images stored at sync time (`previews`)
instead — the same bytes the overview thumbnails already use. A video's
delivery becomes its still frame (Telegram gets a JPEG, not the original
clip): better than nothing, and the only option once the CDN is gone. When
every media index has a stored preview but one is missing, that missing one
means "we truly have nothing to send" — the whole delivery fails loudly
(DeliveryError) rather than silently dropping an item.
"""

from __future__ import annotations

import dataclasses
import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from diffus.crossposting.domain.entities import MediaFile, MediaType, Post
from diffus.crossposting.domain.errors import DeliveryError
from diffus.crossposting.domain.ports import MediaGateway, UnitOfWorkFactory

logger = logging.getLogger(__name__)


@dataclass
class FallbackMediaGateway:
    cdn: MediaGateway
    uow: UnitOfWorkFactory

    @asynccontextmanager
    async def fetch(self, post: Post) -> AsyncIterator[list[MediaFile]]:
        async with AsyncExitStack() as stack:
            files = await self._from_cdn(post, stack)
            if files is None:
                files = await self._from_previews(post, stack)
            # yield outside any try: an exception the caller raises while
            # using `files` must propagate as-is, never be mistaken for a
            # CDN failure and swallowed by the fallback logic above.
            yield files

    async def _from_cdn(self, post: Post, stack: AsyncExitStack) -> list[MediaFile] | None:
        try:
            return await stack.enter_async_context(self.cdn.fetch(post))
        except Exception:
            logger.exception(
                "CDN media fetch failed for post %s; falling back to stored previews", post.id
            )
            return None

    async def _from_previews(self, post: Post, stack: AsyncExitStack) -> list[MediaFile]:
        # The unit of work is only for the read: closed well before the
        # tempdir is written to or the caller does anything with the files.
        async with self.uow() as uow:
            previews = [await uow.previews.get(post.id, i) for i in range(len(post.media))]

        tmpdir = stack.enter_context(tempfile.TemporaryDirectory(prefix="fallback-media-"))
        files: list[MediaFile] = []
        for i, (item, preview) in enumerate(zip(post.media, previews, strict=True)):
            if preview is None:
                raise DeliveryError("Medien nicht mehr verfügbar.")
            path = Path(tmpdir) / f"{post.id}-{i}.jpg"
            path.write_bytes(preview.data)
            if item.type == MediaType.VIDEO:
                # The stored preview is a still frame (a JPEG), never the clip.
                item = dataclasses.replace(item, type=MediaType.IMAGE)
            files.append(MediaFile(item=item, path=path))
        return files

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        """A still-image download (for the sync job's own preview capture) — always the CDN."""
        return await self.cdn.download_image(url)
