"""In-memory fakes implementing the domain ports, for use-case unit tests.

No DB, no network. FakeDeliveries deliberately mirrors the claim/mark semantics
of SqlDeliveryRepository (infrastructure/db/repositories.py) so the application
tests exercise the same retry/exactly-once behaviour the SQL implementation
provides.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from connector.domain.entities import Delivery, DeliveryStatus, Post

MAX_ERROR_LENGTH = 2000


class StaticSource:
    """PostSource that returns a fixed, mutable list of posts."""

    def __init__(self, posts: list[Post]) -> None:
        self.posts = posts

    async def fetch_recent(self, limit: int = 25) -> list[Post]:
        return list(self.posts)[:limit]


class FakePosts:
    def __init__(self) -> None:
        self._posts: dict[str, Post] = {}

    async def upsert(self, post: Post) -> None:
        self._posts.setdefault(post.id, post)  # on_conflict_do_nothing

    async def get(self, post_id: str) -> Post | None:
        return self._posts.get(post_id)

    async def count(self) -> int:
        return len(self._posts)

    async def list_recent(self, limit: int = 20) -> list[Post]:
        return sorted(self._posts.values(), key=lambda p: p.posted_at, reverse=True)[:limit]


class FakeDeliveries:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Delivery] = {}

    async def claim(self, post_id: str, chat_id: str, max_attempts: int = 5) -> bool:
        key = (post_id, chat_id)
        row = self._rows.get(key)
        if row is None:
            self._rows[key] = Delivery(
                post_id=post_id, chat_id=chat_id, status=DeliveryStatus.PENDING, attempts=0
            )
            return True
        return row.status == DeliveryStatus.FAILED and row.attempts < max_attempts

    async def mark(
        self,
        post_id: str,
        chat_id: str,
        status: DeliveryStatus,
        error: str | None = None,
    ) -> None:
        key = (post_id, chat_id)
        row = self._rows.get(key)
        if row is None:
            row = Delivery(post_id=post_id, chat_id=chat_id, status=status, attempts=0)
            self._rows[key] = row

        row.status = status
        if status == DeliveryStatus.SENT:
            row.sent_at = datetime.now(timezone.utc)
            row.error = None
        elif status == DeliveryStatus.FAILED:
            row.attempts += 1
            row.error = (error or "")[:MAX_ERROR_LENGTH]

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]:
        grouped: dict[str, list[Delivery]] = {}
        for (post_id, _chat_id), row in self._rows.items():
            if post_id in post_ids:
                grouped.setdefault(post_id, []).append(row)
        return grouped


class FakeSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def deliver(self, post: Post, chat_id: str, media_paths: Sequence[Path]) -> None:
        self.calls.append((post.id, chat_id))
        if self.fail:
            raise RuntimeError("simulated delivery failure")


class FakeMedia:
    @asynccontextmanager
    async def fetch(self, post: Post):
        yield []
