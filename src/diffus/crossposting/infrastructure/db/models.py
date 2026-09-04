"""SQLAlchemy 2.0 declarative models.

Mirrors alembic/versions/0001_initial.py, 0002_previews.py,
0003_destinations_and_sources.py, 0005_drafts_and_scopes.py and
0006_freigabe_and_channels.py exactly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from diffus.shared.db.base import Base


class TokenRow(Base):
    """A source's long-lived credential, one row per source.

    Mirrors alembic/versions/0003_destinations_and_sources.py and the
    `scopes` column added in 0005_drafts_and_scopes.py.
    """

    __tablename__ = "tokens"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)


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

    Mirrors alembic/versions/0003_destinations_and_sources.py; the status
    index is 0006_freigabe_and_channels.py (the Freigabe queue and its nav
    badge filter by status on every request).
    """

    __tablename__ = "deliveries"
    __table_args__ = (Index("ix_deliveries_status", "status"),)

    post_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("posts.id"), primary_key=True
    )
    sink: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PostDraftRow(Base):
    """A post being composed. Mirrors alembic/versions/0005_drafts_and_scopes.py.

    `post_id` has no foreign key: the post it produces is created only once
    publishing succeeds, and the draft outlives it as an audit trail (see the
    migration docstring).
    """

    __tablename__ = "post_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Freigabe (0006_freigabe_and_channels.py): what PublishTargets looked
    # like at submit time — {"instagram": bool, "destinations": [...]}  —
    # and "calendar:<event id>" for a draft started from an event.
    targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    event_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)


class PostDraftMediaRow(Base):
    """One uploaded, normalised draft image. Mirrors alembic/versions/0005_drafts_and_scopes.py."""

    __tablename__ = "post_draft_media"

    draft_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("post_drafts.id", ondelete="CASCADE"), primary_key=True
    )
    media_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class ChannelSettingRow(Base):
    """Per-channel auto-publish switch. Mirrors alembic/versions/0006_freigabe_and_channels.py.

    `destination` is a Destination's text form ("telegram:-100…",
    "instagram:account"); a missing row means "not auto" — the default is
    off, not a NULL/False column, so `channel_settings` only ever holds
    channels someone has actually touched.
    """

    __tablename__ = "channel_settings"

    destination: Mapped[str] = mapped_column(String(100), primary_key=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False)
