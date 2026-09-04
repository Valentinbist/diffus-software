"""MediaGateway over a draft's own (already normalised) images.

DeliverPost needs a MediaGateway to hand a sink some local files, but a
draft's images already live in the database — nothing to download over the
network. Unlike HttpMediaGateway (infrastructure/media/downloader.py), this
one is built per draft, at publish time, by PublishDraft itself — so it lives
next to that use case instead of in infrastructure/, which only ever holds
adapters the composition root wires once at startup.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from diffus.crossposting.domain.entities import MediaFile, Post, PostDraft


@dataclass
class DraftMediaGateway:
    draft: PostDraft

    @asynccontextmanager
    async def fetch(self, post: Post) -> AsyncIterator[list[MediaFile]]:
        with tempfile.TemporaryDirectory(prefix="draft-media-") as tmpdir:
            files: list[MediaFile] = []
            for i, image in enumerate(self.draft.images):
                path = Path(tmpdir) / f"{post.id}-{i}.jpg"
                path.write_bytes(image.data)
                files.append(MediaFile(item=post.media[i], path=path))
            yield files

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        """A draft's images are never re-downloaded from anywhere."""
        return None
