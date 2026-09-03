"""SQLAlchemy implementations of the domain repository ports.

Each method opens and closes its own session/transaction — these repositories
are not unit-of-work objects, the use cases call them one at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from connector.domain.entities import (
    Delivery,
    DeliveryStatus,
    MediaItem,
    MediaType,
    Post,
    Preview,
    Token,
)
from connector.infrastructure.db.models import DeliveryRow, PostRow, PreviewRow, TokenRow

MAX_ERROR_LENGTH = 2000


def _post_to_row(post: Post) -> dict:
    return {
        "id": post.id,
        "caption": post.caption,
        "permalink": post.permalink,
        "media": [
            {"url": m.url, "type": m.type.value, "thumbnail_url": m.thumbnail_url}
            for m in post.media
        ],
        "posted_at": post.posted_at,
    }


def _row_to_post(row: PostRow) -> Post:
    return Post(
        id=row.id,
        caption=row.caption,
        permalink=row.permalink,
        media=tuple(
            # .get(): rows written before thumbnails were stored have no such key.
            MediaItem(
                url=m["url"], type=MediaType(m["type"]), thumbnail_url=m.get("thumbnail_url")
            )
            for m in row.media
        ),
        posted_at=row.posted_at,
    )


def _row_to_delivery(row: DeliveryRow) -> Delivery:
    return Delivery(
        post_id=row.post_id,
        chat_id=row.chat_id,
        status=DeliveryStatus(row.status),
        attempts=row.attempts,
        sent_at=row.sent_at,
        error=row.error,
    )


def _row_to_token(row: TokenRow) -> Token:
    return Token(
        access_token=row.access_token,
        ig_user_id=row.ig_user_id,
        expires_at=row.expires_at,
        refreshed_at=row.refreshed_at,
    )


class SqlPostRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert(self, post: Post) -> None:
        async with self._sf() as s, s.begin():
            stmt = pg_insert(PostRow).values(**_post_to_row(post))
            stmt = stmt.on_conflict_do_nothing(index_elements=[PostRow.id])
            await s.execute(stmt)

    async def get(self, post_id: str) -> Post | None:
        async with self._sf() as s:
            row = await s.get(PostRow, post_id)
            return _row_to_post(row) if row is not None else None

    async def count(self) -> int:
        async with self._sf() as s:
            result = await s.execute(select(func.count()).select_from(PostRow))
            return int(result.scalar_one())

    async def list_recent(self, limit: int = 20) -> list[Post]:
        async with self._sf() as s:
            result = await s.execute(
                select(PostRow).order_by(PostRow.posted_at.desc()).limit(limit)
            )
            return [_row_to_post(row) for row in result.scalars().all()]


class SqlDeliveryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def claim(self, post_id: str, chat_id: str, max_attempts: int = 5) -> bool:
        async with self._sf() as s, s.begin():
            stmt = (
                pg_insert(DeliveryRow)
                .values(
                    post_id=post_id,
                    chat_id=chat_id,
                    status=DeliveryStatus.PENDING.value,
                    attempts=0,
                )
                .on_conflict_do_nothing(index_elements=[DeliveryRow.post_id, DeliveryRow.chat_id])
                # RETURNING yields a row only when the insert actually happened,
                # so "did we just claim this?" is answered without touching rowcount.
                .returning(DeliveryRow.post_id)
            )
            inserted = (await s.execute(stmt)).scalar_one_or_none()
            if inserted is not None:
                return True

            row = await s.get(DeliveryRow, (post_id, chat_id))
            if row is None:
                return False
            return row.status == DeliveryStatus.FAILED.value and row.attempts < max_attempts

    async def mark(
        self,
        post_id: str,
        chat_id: str,
        status: DeliveryStatus,
        error: str | None = None,
    ) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(DeliveryRow, (post_id, chat_id))
            if row is None:
                row = DeliveryRow(
                    post_id=post_id, chat_id=chat_id, status=status.value, attempts=0
                )
                s.add(row)

            row.status = status.value
            if status == DeliveryStatus.SENT:
                row.sent_at = datetime.now(UTC)
                row.error = None
            elif status == DeliveryStatus.FAILED:
                row.attempts += 1
                row.error = (error or "")[:MAX_ERROR_LENGTH]

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]:
        if not post_ids:
            return {}
        async with self._sf() as s:
            result = await s.execute(
                select(DeliveryRow).where(DeliveryRow.post_id.in_(post_ids))
            )
            grouped: dict[str, list[Delivery]] = {}
            for row in result.scalars().all():
                grouped.setdefault(row.post_id, []).append(_row_to_delivery(row))
            return grouped


class SqlPreviewRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save(self, preview: Preview) -> None:
        async with self._sf() as s, s.begin():
            stmt = pg_insert(PreviewRow).values(
                post_id=preview.post_id,
                media_index=preview.index,
                content_type=preview.content_type,
                data=preview.data,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[PreviewRow.post_id, PreviewRow.media_index],
                set_={
                    "content_type": stmt.excluded.content_type,
                    "data": stmt.excluded.data,
                    "fetched_at": func.now(),
                },
            )
            await s.execute(stmt)

    async def get(self, post_id: str, index: int) -> Preview | None:
        async with self._sf() as s:
            row = await s.get(PreviewRow, (post_id, index))
            if row is None:
                return None
            return Preview(
                post_id=row.post_id,
                index=row.media_index,
                content_type=row.content_type,
                data=row.data,
            )

    async def stored(self, post_ids: Sequence[str]) -> dict[str, frozenset[int]]:
        if not post_ids:
            return {}
        async with self._sf() as s:
            result = await s.execute(
                select(PreviewRow.post_id, PreviewRow.media_index).where(
                    PreviewRow.post_id.in_(post_ids)
                )
            )
            grouped: dict[str, set[int]] = {}
            for post_id, index in result.all():
                grouped.setdefault(post_id, set()).add(index)
            return {post_id: frozenset(indexes) for post_id, indexes in grouped.items()}


class SqlTokenRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self) -> Token | None:
        async with self._sf() as s:
            row = await s.get(TokenRow, 1)
            return _row_to_token(row) if row is not None else None

    async def save(self, token: Token) -> None:
        async with self._sf() as s, s.begin():
            await s.merge(
                TokenRow(
                    id=1,
                    access_token=token.access_token,
                    ig_user_id=token.ig_user_id,
                    expires_at=token.expires_at,
                    refreshed_at=token.refreshed_at,
                )
            )
