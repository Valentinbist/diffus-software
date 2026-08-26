"""Downloads Instagram CDN media to a local tempdir. Implements MediaGateway."""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx

from connector.domain.entities import MediaType, Post


class HttpMediaGateway:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    @asynccontextmanager
    async def fetch(self, post: Post) -> AsyncIterator[list[Path]]:
        with tempfile.TemporaryDirectory(prefix="connector-media-") as tmpdir:
            paths: list[Path] = []
            for i, media_item in enumerate(post.media):
                ext = "mp4" if media_item.type == MediaType.VIDEO else "jpg"
                path = Path(tmpdir) / f"{post.id}-{i}.{ext}"
                async with self.http.stream("GET", media_item.url) as resp:
                    resp.raise_for_status()
                    with path.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                paths.append(path)
            yield paths
