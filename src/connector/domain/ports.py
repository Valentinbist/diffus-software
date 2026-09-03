"""Ports (protocols) the application layer depends on. Stdlib only.

Infrastructure adapters implement these protocols; the application layer
depends only on these abstractions, never on concrete infrastructure.

A UnitOfWork groups the repository writes of one use case into a single
persistence boundary: it never spans a network call. Writes commit
explicitly via `commit()`; reads never commit.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol, Self

from connector.domain.entities import Delivery, Destination, MediaFile, Post, Preview, Token


class PostSource(Protocol):
    source: str

    async def fetch_recent(self, token: Token, limit: int = 25) -> list[Post]: ...


class PostSink(Protocol):
    async def deliver(
        self, post: Post, address: str, media: Sequence[MediaFile]
    ) -> None: ...


class MediaGateway(Protocol):
    def fetch(self, post: Post) -> AbstractAsyncContextManager[list[MediaFile]]: ...

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        """(content type, bytes) of an image, or None if the URL isn't a reasonably sized image."""
        ...


class AuthGateway(Protocol):
    source: str

    def authorize_url(self) -> str: ...

    async def exchange_code(self, code: str) -> Token: ...

    async def refresh(self, token: Token) -> Token: ...


class PostRepository(Protocol):
    async def upsert(self, post: Post) -> None: ...

    async def get(self, post_id: str) -> Post | None: ...

    async def count(self) -> int: ...

    async def list_recent(self, limit: int = 20) -> list[Post]: ...


class DeliveryRepository(Protocol):
    async def claim(self, post_id: str, destination: Destination) -> Delivery | None:
        """Claim the right to (re)try this delivery, or None if it isn't claimable.

        A fresh (post_id, destination) pair is always claimable. An existing
        row is claimable again only while its own `Delivery.can_retry()` says
        so — the retry policy lives on the entity, not here.
        """
        ...

    async def save(self, delivery: Delivery) -> None: ...

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]: ...


class PreviewRepository(Protocol):
    async def save(self, preview: Preview) -> None: ...

    async def get(self, post_id: str, index: int) -> Preview | None: ...

    async def stored(self, post_ids: Sequence[str]) -> dict[str, frozenset[int]]:
        """Which media indexes of each post already have a stored preview."""
        ...


class TokenRepository(Protocol):
    async def get(self, source: str) -> Token | None: ...

    async def save(self, token: Token) -> None: ...


class UnitOfWork(Protocol):
    posts: PostRepository
    deliveries: DeliveryRepository
    previews: PreviewRepository
    tokens: TokenRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
