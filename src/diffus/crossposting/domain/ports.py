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

from diffus.crossposting.domain.entities import (
    Delivery,
    Destination,
    DraftImage,
    LinkedEvent,
    MediaFile,
    Post,
    PostDraft,
    Preview,
    Token,
)


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


class EventDirectory(Protocol):
    """Read-only window onto the calendar context's events, keyed by post."""

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[LinkedEvent]]: ...


class ImageProcessor(Protocol):
    def normalise(self, data: bytes) -> DraftImage:
        """Decode, orient, crop, re-encode one upload. Sync/CPU-bound; raises InvalidImageError."""
        ...


class DraftRepository(Protocol):
    async def add(self, draft: PostDraft) -> None:
        """Insert the draft row and one row per image. Only ever called once per draft."""
        ...

    async def update(self, draft: PostDraft) -> None:
        """Persist status/error/post_id/published_at. Images are immutable after add()."""
        ...

    async def get(self, draft_id: str) -> PostDraft | None:
        """The draft with its images, ordered by index."""
        ...

    async def get_image(self, draft_id: str, index: int) -> DraftImage | None: ...

    async def public_key(self, draft_id: str) -> str | None:
        """Just the key column, for the unauthenticated media route."""
        ...

    async def delete(self, draft_id: str) -> None: ...


class MediaPublisher(Protocol):
    """Publishes a draft's images to a source and reads the resulting post back."""

    source: str

    async def publish_images(self, token: Token, image_urls: Sequence[str], caption: str) -> str:
        """Creates a (carousel) container, waits for it, publishes it. Returns the media id."""
        ...

    async def fetch_post(self, token: Token, post_id: str) -> Post: ...


class UnitOfWork(Protocol):
    posts: PostRepository
    deliveries: DeliveryRepository
    previews: PreviewRepository
    tokens: TokenRepository
    drafts: DraftRepository

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
