"""In-memory fakes implementing the domain ports, for use-case unit tests.

No DB, no network. FakeUnitOfWork wires the four fake repositories together
the way SqlUnitOfWork wires the real ones. Every fake repository's write
methods set `dirty = True`; FakeUnitOfWork.__aexit__ raises if it is exited
cleanly while any repository is still dirty, so a use case that forgets to
call commit() fails its test instead of silently passing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

from diffus.crossposting.domain.entities import (
    AccessToken,
    Delivery,
    Destination,
    LinkedEvent,
    MediaFile,
    Post,
    Preview,
    Token,
)
from diffus.crossposting.domain.ports import (
    DeliveryRepository,
    PostRepository,
    PreviewRepository,
    TokenRepository,
)


class StaticSource:
    """PostSource that returns a fixed, mutable list of posts."""

    source = "instagram"

    def __init__(self, posts: list[Post]) -> None:
        self.posts = posts

    async def fetch_recent(self, token: Token, limit: int = 25) -> list[Post]:
        return list(self.posts)[:limit]


class FailingSource:
    """PostSource that raises, the way InstagramClient does on an API error."""

    source = "instagram"

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def fetch_recent(self, token: Token, limit: int = 25) -> list[Post]:
        raise self.error


class FakePosts:
    def __init__(self) -> None:
        self._posts: dict[str, Post] = {}
        self.dirty = False

    async def upsert(self, post: Post) -> None:
        self._posts.setdefault(post.id, post)  # on_conflict_do_nothing
        self.dirty = True

    async def get(self, post_id: str) -> Post | None:
        return self._posts.get(post_id)

    async def count(self) -> int:
        return len(self._posts)

    async def list_recent(self, limit: int = 20) -> list[Post]:
        return sorted(self._posts.values(), key=lambda p: p.posted_at, reverse=True)[:limit]


class FakeDeliveries:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, Destination], Delivery] = {}
        self.dirty = False

    async def claim(self, post_id: str, destination: Destination) -> Delivery | None:
        # Always a copy: mutating a delivery the caller got back must never
        # silently update the stored row — only an explicit save() may do that,
        # the way a detached ORM instance needs an explicit merge().
        key = (post_id, destination)
        row = self._rows.get(key)
        if row is None:
            row = Delivery(post_id=post_id, destination=destination)
            self._rows[key] = row
            self.dirty = True
            return dataclasses.replace(row)
        return dataclasses.replace(row) if row.can_retry() else None

    async def save(self, delivery: Delivery) -> None:
        self._rows[(delivery.post_id, delivery.destination)] = dataclasses.replace(delivery)
        self.dirty = True

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]:
        grouped: dict[str, list[Delivery]] = {}
        for (post_id, _destination), row in self._rows.items():
            if post_id in post_ids:
                grouped.setdefault(post_id, []).append(dataclasses.replace(row))
        return grouped


class FakeSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def deliver(self, post: Post, address: str, media: Sequence[MediaFile]) -> None:
        self.calls.append((post.id, address))
        if self.fail:
            raise RuntimeError("simulated delivery failure")


class FakeMedia:
    """MediaGateway with no files and an in-memory map of downloadable images."""

    def __init__(self, images: dict[str, bytes] | None = None, fail_images: bool = False) -> None:
        self.images = images or {}
        self.fail_images = fail_images
        self.downloads: list[str] = []

    @asynccontextmanager
    async def fetch(self, post: Post) -> AsyncIterator[list[MediaFile]]:
        yield []

    async def download_image(self, url: str) -> tuple[str, bytes] | None:
        self.downloads.append(url)
        if self.fail_images:
            raise RuntimeError("simulated download failure")
        data = self.images.get(url)
        return ("image/jpeg", data) if data is not None else None


class FakePreviews:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], Preview] = {}
        self.dirty = False

    async def save(self, preview: Preview) -> None:
        self._rows[(preview.post_id, preview.index)] = preview
        self.dirty = True

    async def get(self, post_id: str, index: int) -> Preview | None:
        return self._rows.get((post_id, index))

    async def stored(self, post_ids: Sequence[str]) -> dict[str, frozenset[int]]:
        grouped: dict[str, set[int]] = {}
        for post_id, index in self._rows:
            if post_id in post_ids:
                grouped.setdefault(post_id, set()).add(index)
        return {post_id: frozenset(indexes) for post_id, indexes in grouped.items()}


class FakeTokens:
    def __init__(self, token: Token | None = None) -> None:
        self._tokens: dict[str, Token] = {token.source: token} if token is not None else {}
        self.dirty = False

    @property
    def token(self) -> Token | None:
        """Convenience for tests with a single stored token: the one row, or None."""
        return next(iter(self._tokens.values()), None)

    async def get(self, source: str) -> Token | None:
        return self._tokens.get(source)

    async def save(self, token: Token) -> None:
        self._tokens[token.source] = token
        self.dirty = True


class FakeEventDirectory:
    """EventDirectory over a fixed mapping, the way a real calendar-context adapter would answer."""

    def __init__(self, mapping: dict[str, list[LinkedEvent]] | None = None) -> None:
        self.mapping = mapping or {}

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[LinkedEvent]]:
        return {post_id: self.mapping[post_id] for post_id in post_ids if post_id in self.mapping}


class FakeAuth:
    """AuthGateway that stamps a fresh 60-day token on every refresh."""

    source = "instagram"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.refresh_calls = 0
        self.exchanged_codes: list[str] = []

    def authorize_url(self) -> str:
        return "https://example.com/authorize"

    async def exchange_code(self, code: str) -> Token:
        self.exchanged_codes.append(code)
        now = datetime.now(UTC)
        return Token(
            source=self.source,
            access_token=AccessToken(f"exchanged-{code}"),
            external_user_id="1",
            expires_at=now + timedelta(days=60),
            refreshed_at=now,
        )

    async def refresh(self, token: Token) -> Token:
        self.refresh_calls += 1
        if self.fail:
            raise RuntimeError("simulated refresh failure")
        now = datetime.now(UTC)
        return Token(
            source=token.source,
            access_token=AccessToken("refreshed"),
            external_user_id=token.external_user_id,
            expires_at=now + timedelta(days=60),
            refreshed_at=now,
        )


class FakeUnitOfWork:
    """UnitOfWork over the fake repositories.

    Re-enterable, and callable with no arguments returning itself, so the
    same instance doubles as the `UnitOfWorkFactory` a use case is given
    (`uow=uow`). `__aexit__` raises if a caller forgot to `commit()` a write.
    """

    def __init__(
        self,
        posts: FakePosts | None = None,
        deliveries: FakeDeliveries | None = None,
        previews: FakePreviews | None = None,
        tokens: FakeTokens | None = None,
    ) -> None:
        # Kept as concrete types privately so __aexit__/commit/rollback can flip
        # `dirty`; exposed publicly at the Protocol type, like SqlUnitOfWork's
        # repositories, so ty checks use cases against the port, not the fake.
        self._posts = posts if posts is not None else FakePosts()
        self._deliveries = deliveries if deliveries is not None else FakeDeliveries()
        self._previews = previews if previews is not None else FakePreviews()
        self._tokens = tokens if tokens is not None else FakeTokens()
        self.posts: PostRepository = self._posts
        self.deliveries: DeliveryRepository = self._deliveries
        self.previews: PreviewRepository = self._previews
        self.tokens: TokenRepository = self._tokens
        self.commits = 0

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        dirty = (
            self._posts.dirty
            or self._deliveries.dirty
            or self._previews.dirty
            or self._tokens.dirty
        )
        try:
            if exc_type is None and dirty:
                raise AssertionError("unit of work exited with uncommitted writes")
        finally:
            self._clear_dirty()

    async def commit(self) -> None:
        self.commits += 1
        self._clear_dirty()

    async def rollback(self) -> None:
        self._clear_dirty()

    def _clear_dirty(self) -> None:
        self._posts.dirty = False
        self._deliveries.dirty = False
        self._previews.dirty = False
        self._tokens.dirty = False
