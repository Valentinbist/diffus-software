"""Ports (protocols) the application layer depends on. Stdlib only.

Infrastructure adapters implement these protocols; the application layer
depends only on these abstractions, never on concrete infrastructure.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

from connector.domain.entities import Delivery, DeliveryStatus, Post, Preview, Token


class PostSource(Protocol):
    async def fetch_recent(self, limit: int = 25) -> list[Post]: ...


class PostSink(Protocol):
    async def deliver(
        self, post: Post, chat_id: str, media_paths: Sequence[Path]
    ) -> None: ...


class MediaGateway(Protocol):
    def fetch(self, post: Post) -> AbstractAsyncContextManager[list[Path]]: ...

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        """(content type, bytes) of an image, or None if the URL isn't a reasonably sized image."""
        ...


class AuthGateway(Protocol):
    def authorize_url(self) -> str: ...

    async def exchange_code(self, code: str) -> Token: ...

    async def refresh(self, token: Token) -> Token: ...


class PostRepository(Protocol):
    async def upsert(self, post: Post) -> None: ...

    async def get(self, post_id: str) -> Post | None: ...

    async def count(self) -> int: ...

    async def list_recent(self, limit: int = 20) -> list[Post]: ...


class DeliveryRepository(Protocol):
    async def claim(
        self, post_id: str, chat_id: str, max_attempts: int = 5
    ) -> bool: ...

    async def mark(
        self,
        post_id: str,
        chat_id: str,
        status: DeliveryStatus,
        error: str | None = None,
    ) -> None: ...

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]: ...


class PreviewRepository(Protocol):
    async def save(self, preview: Preview) -> None: ...

    async def get(self, post_id: str, index: int) -> Preview | None: ...

    async def stored(self, post_ids: Sequence[str]) -> dict[str, frozenset[int]]:
        """Which media indexes of each post already have a stored preview."""
        ...


class TokenRepository(Protocol):
    async def get(self) -> Token | None: ...

    async def save(self, token: Token) -> None: ...
