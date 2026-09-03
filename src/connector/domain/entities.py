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
    # Instagram supplies a still frame for videos; images are their own preview.
    thumbnail_url: str | None = None

    @property
    def preview_url(self) -> str | None:
        """Best URL for a still preview, or None when the item has no usable image."""
        if self.thumbnail_url:
            return self.thumbnail_url
        return self.url if self.type == MediaType.IMAGE else None


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    caption: str | None
    permalink: str
    media: tuple[MediaItem, ...]
    posted_at: datetime

    @property
    def cover_url(self) -> str | None:
        """Preview of the first media item that has one, for thumbnails in the UI."""
        return next((m.preview_url for m in self.media if m.preview_url), None)


@dataclass(frozen=True, slots=True)
class Preview:
    """A media item's still image, kept by the connector because CDN links expire."""

    post_id: str
    index: int
    content_type: str
    data: bytes


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
