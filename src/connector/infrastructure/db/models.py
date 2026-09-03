"""SQLAlchemy 2.0 declarative models.

Mirrors alembic/versions/0001_initial.py, 0002_previews.py and
0003_destinations_and_sources.py exactly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TokenRow(Base):
    """A source's long-lived credential, one row per source.

    Mirrors alembic/versions/0003_destinations_and_sources.py.
    """

    __tablename__ = "tokens"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PostRow(Base):
    """Mirrors alembic/versions/0003_destinations_and_sources.py."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    permalink: Mapped[str] = mapped_column(Text, nullable=False)
    media: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PreviewRow(Base):
    """A stored still image per media item. Mirrors alembic/versions/0002_previews.py."""

    __tablename__ = "previews"

    post_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("posts.id"), primary_key=True
    )
    media_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeliveryRow(Base):
    """One post's delivery to one destination.

    Mirrors alembic/versions/0003_destinations_and_sources.py.
    """

    __tablename__ = "deliveries"

    post_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("posts.id"), primary_key=True
    )
    sink: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
