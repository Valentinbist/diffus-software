"""SQLAlchemy 2.0 declarative models.

Mirrors alembic/versions/0004_calendar.py exactly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from diffus.shared.db.base import Base


class SubCalendarRow(Base):
    """Mirrors alembic/versions/0004_calendar.py."""

    __tablename__ = "calendar_sub_calendars"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class EventRow(Base):
    """Mirrors alembic/versions/0004_calendar.py."""

    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    who: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    whole_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    series_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventSubCalendarRow(Base):
    """Mirrors alembic/versions/0004_calendar.py. No relationship(): repositories join by hand."""

    __tablename__ = "calendar_event_sub_calendars"

    event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True
    )
    sub_calendar_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("calendar_sub_calendars.id", ondelete="CASCADE"),
        primary_key=True,
    )


class EventPostRow(Base):
    """Mirrors alembic/versions/0004_calendar.py.

    post_id has no foreign key: the post lives in the crossposting context's
    posts table (see the migration docstring).
    """

    __tablename__ = "calendar_event_posts"

    event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
