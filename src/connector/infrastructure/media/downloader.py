"""Downloads Instagram CDN media. Implements MediaGateway."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from connector.domain.entities import MediaFile, MediaType, Post

# Instagram stills are a few hundred KB; anything past this isn't a preview.
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class HttpMediaGateway:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    @asynccontextmanager
    async def fetch(self, post: Post) -> AsyncIterator[list[MediaFile]]:
        """All media of a post as temp files, for handing to Telegram."""
        with tempfile.TemporaryDirectory(prefix="connector-media-") as tmpdir:
            files: list[MediaFile] = []
            for i, media_item in enumerate(post.media):
                ext = "mp4" if media_item.type == MediaType.VIDEO else "jpg"
                path = Path(tmpdir) / f"{post.id}-{i}.{ext}"
                async with self.http.stream("GET", media_item.url) as resp:
                    resp.raise_for_status()
                    with path.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                files.append(MediaFile(item=media_item, path=path))
            yield files

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        """One still image into memory, or None if the URL doesn't serve a sane image."""
        async with self.http.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                return None
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
                return None

            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
            return content_type, b"".join(chunks)
