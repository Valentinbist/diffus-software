"""Core domain entities and value objects. Stdlib only — no external dependencies allowed here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import ClassVar


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
class MediaFile:
    """One media item downloaded to a local file — the shape sinks receive."""

    item: MediaItem
    path: Path


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    source: str
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


@dataclass(frozen=True, slots=True, order=True)
class Destination:
    """Where a post goes: a sink by name, and an address that sink understands.

    The text form is "<sink>:<address>", e.g. "telegram:-1001234567890"; it is
    what forms and URLs carry. Sink names never contain ":", addresses may.
    """

    sink: str
    address: str

    def __str__(self) -> str:
        return f"{self.sink}:{self.address}"

    @classmethod
    def parse(cls, text: str) -> Destination:
        sink, sep, address = text.partition(":")
        if not sep or not sink or not address:
            raise ValueError(f"not a destination: {text!r}")
        return cls(sink=sink, address=address)


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Delivery:
    """The state of getting one post to one destination.

    Owns the retry policy: a failed delivery is tried again on every sync
    until MAX_ATTEMPTS; a sent or skipped one is never touched again.
    """

    MAX_ATTEMPTS: ClassVar[int] = 5
    MAX_ERROR_LENGTH: ClassVar[int] = 2000

    post_id: str
    destination: Destination
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    sent_at: datetime | None = None
    error: str | None = None

    def can_retry(self) -> bool:
        return self.status == DeliveryStatus.FAILED and self.attempts < self.MAX_ATTEMPTS

    def record_sent(self, now: datetime) -> None:
        self.status = DeliveryStatus.SENT
        self.sent_at = now
        self.error = None

    def record_failure(self, error: str) -> None:
        self.status = DeliveryStatus.FAILED
        self.attempts += 1
        self.error = error[: self.MAX_ERROR_LENGTH]

    def skip(self) -> None:
        """Seen, deliberately not sent — what the first sync does with existing posts."""
        self.status = DeliveryStatus.SKIPPED


@dataclass(frozen=True, slots=True)
class LinkedEvent:
    """The connector's own view of a calendar event, via EventDirectory.

    Mirrors calendar.domain.entities.LinkablePost the other way round: a
    context never imports another context's domain, so each side has its
    own tiny read model of the other's entity.
    """

    id: str
    title: str
    starts_at: datetime
    detail_url: str
    removed: bool = False


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A bearer secret. Never shows its text in reprs, logs or f-strings; use .value on the wire."""

    value: str

    def __repr__(self) -> str:
        return "AccessToken(…)"

    def __str__(self) -> str:
        return "AccessToken(…)"


@dataclass(frozen=True, slots=True)
class Token:
    """A source's long-lived credential.

    The refresh policy follows Instagram's 60-day tokens: refresh on a timer
    well before expiry, and in any case when expiry gets close.
    """

    REFRESH_AFTER_DAYS: ClassVar[int] = 50
    REFRESH_WITHIN_EXPIRY_DAYS: ClassVar[int] = 7

    source: str
    access_token: AccessToken
    external_user_id: str | None
    expires_at: datetime
    refreshed_at: datetime

    def needs_refresh(self, now: datetime) -> bool:
        return (
            now - self.refreshed_at >= timedelta(days=self.REFRESH_AFTER_DAYS)
            or self.expires_at - now <= timedelta(days=self.REFRESH_WITHIN_EXPIRY_DAYS)
        )
