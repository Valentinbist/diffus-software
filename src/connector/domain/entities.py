"""Core domain entities. Stdlib only — no external dependencies allowed here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class MediaItem:
    url: str
    type: MediaType


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    caption: str | None
    permalink: str
    media: tuple[MediaItem, ...]
    posted_at: datetime


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Delivery:
    post_id: str
    chat_id: str
    status: DeliveryStatus
    attempts: int = 0
    sent_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Token:
    access_token: str
    ig_user_id: str | None
    expires_at: datetime
    refreshed_at: datetime
