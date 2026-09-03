"""SQLAlchemy implementations of the domain repository ports.

Repositories are bound to a unit of work: each one wraps a single AsyncSession
(see infrastructure/db/uow.py) and never opens or commits a transaction
itself — the surrounding UnitOfWork does that. `claim` stays atomic even
without an explicit transaction because the `INSERT ... ON CONFLICT ...
RETURNING` is a single statement.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from connector.domain.entities import (
    AccessToken,
    Delivery,
    DeliveryStatus,
    Destination,
    MediaItem,
    MediaType,
    Post,
    Preview,
    Token,
)
from connector.infrastructure.db.models import DeliveryRow, PostRow, PreviewRow, TokenRow


def _post_to_row(post: Post) -> dict:
    return {
        "id": post.id,
        "source": post.source,
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
        source=row.source,
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
        destination=Destination(row.sink, row.address),
        status=DeliveryStatus(row.status),
        attempts=row.attempts,
        sent_at=row.sent_at,
        error=row.error,
    )


def _delivery_to_row(delivery: Delivery) -> DeliveryRow:
    return DeliveryRow(
        post_id=delivery.post_id,
        sink=delivery.destination.sink,
        address=delivery.destination.address,
        status=delivery.status.value,
        attempts=delivery.attempts,
        sent_at=delivery.sent_at,
        error=delivery.error,
    )


def _row_to_token(row: TokenRow) -> Token:
    return Token(
        source=row.source,
        access_token=AccessToken(row.access_token),
        external_user_id=row.external_user_id,
        expires_at=row.expires_at,
        refreshed_at=row.refreshed_at,
    )


class SqlPostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, post: Post) -> None:
        stmt = pg_insert(PostRow).values(**_post_to_row(post))
        stmt = stmt.on_conflict_do_nothing(index_elements=[PostRow.id])
        await self._s.execute(stmt)

    async def get(self, post_id: str) -> Post | None:
        row = await self._s.get(PostRow, post_id)
        return _row_to_post(row) if row is not None else None

    async def count(self) -> int:
        result = await self._s.execute(select(func.count()).select_from(PostRow))
        return int(result.scalar_one())

    async def list_recent(self, limit: int = 20) -> list[Post]:
        result = await self._s.execute(
            select(PostRow).order_by(PostRow.posted_at.desc()).limit(limit)
        )
        return [_row_to_post(row) for row in result.scalars().all()]


class SqlDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def claim(self, post_id: str, destination: Destination) -> Delivery | None:
        stmt = (
            pg_insert(DeliveryRow)
            .values(
                post_id=post_id,
                sink=destination.sink,
                address=destination.address,
                status=DeliveryStatus.PENDING.value,
                attempts=0,
            )
            .on_conflict_do_nothing(
                index_elements=[DeliveryRow.post_id, DeliveryRow.sink, DeliveryRow.address]
            )
            # RETURNING yields a row only when the insert actually happened,
            # so "did we just claim this?" is answered without touching rowcount.
            .returning(DeliveryRow.post_id)
        )
        inserted = (await self._s.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            return Delivery(post_id=post_id, destination=destination)

        row = await self._s.get(DeliveryRow, (post_id, destination.sink, destination.address))
        if row is None:
            return None
        delivery = _row_to_delivery(row)
        return delivery if delivery.can_retry() else None

    async def save(self, delivery: Delivery) -> None:
        await self._s.merge(_delivery_to_row(delivery))

    async def for_posts(self, post_ids: Sequence[str]) -> dict[str, list[Delivery]]:
        if not post_ids:
            return {}
        result = await self._s.execute(
            select(DeliveryRow).where(DeliveryRow.post_id.in_(post_ids))
        )
        grouped: dict[str, list[Delivery]] = {}
        for row in result.scalars().all():
            grouped.setdefault(row.post_id, []).append(_row_to_delivery(row))
        return grouped


class SqlPreviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, preview: Preview) -> None:
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
        await self._s.execute(stmt)

    async def get(self, post_id: str, index: int) -> Preview | None:
        row = await self._s.get(PreviewRow, (post_id, index))
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
        result = await self._s.execute(
            select(PreviewRow.post_id, PreviewRow.media_index).where(
                PreviewRow.post_id.in_(post_ids)
            )
        )
        grouped: dict[str, set[int]] = {}
        for post_id, index in result.all():
            grouped.setdefault(post_id, set()).add(index)
        return {post_id: frozenset(indexes) for post_id, indexes in grouped.items()}


class SqlTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, source: str) -> Token | None:
        row = await self._s.get(TokenRow, source)
        return _row_to_token(row) if row is not None else None

    async def save(self, token: Token) -> None:
        await self._s.merge(
            TokenRow(
                source=token.source,
                access_token=token.access_token.value,
                external_user_id=token.external_user_id,
                expires_at=token.expires_at,
                refreshed_at=token.refreshed_at,
            )
        )
