"""Core domain entities and value objects. Stdlib only — no external dependencies allowed here."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
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
    # Freigabe: queued for a human to approve before it is ever sent. Only a
    # PENDING delivery can be queued, and only a REVIEW one approved/rejected
    # — see Delivery.queue_for_review/approve/reject.
    REVIEW = "review"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Delivery:
    """The state of getting one post to one destination.

    Owns the retry policy: a failed delivery is tried again on every sync
    until MAX_ATTEMPTS; a sent or skipped one is never touched again. Owns
    the Freigabe state machine too: PENDING -> REVIEW -> {PENDING, SKIPPED}
    via queue_for_review/approve/reject — each raises ValueError from any
    other status, the same way a stray transition would corrupt the retry
    policy above. can_retry() is deliberately unchanged: a REVIEW row is
    never FAILED, so it is never retried by the poller (see docs/architecture.md,
    Sharp edges) until a human approves or rejects it.
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

    def queue_for_review(self) -> None:
        """A fresh delivery to a non-auto channel waits for a human instead of sending."""
        if self.status != DeliveryStatus.PENDING:
            raise ValueError(f"cannot queue for review from {self.status}")
        self.status = DeliveryStatus.REVIEW

    def approve(self) -> None:
        """A human chose this destination: back to PENDING, so the normal delivery path sends it."""
        if self.status != DeliveryStatus.REVIEW:
            raise ValueError(f"cannot approve from {self.status}")
        self.status = DeliveryStatus.PENDING

    def reject(self) -> None:
        """A human did not choose this destination: SKIPPED, like the first-sync bootstrap."""
        if self.status != DeliveryStatus.REVIEW:
            raise ValueError(f"cannot reject from {self.status}")
        self.status = DeliveryStatus.SKIPPED


class DraftStatus(StrEnum):
    DRAFT = "draft"
    # Freigabe: submitted with targets chosen, waiting for a human — see
    # PostDraft.submit_for_review/is_reviewable.
    REVIEW = "review"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DraftImage:
    """One uploaded image, already normalised. Always image/jpeg — see PillowImageProcessor."""

    content_type: str
    width: int
    height: int
    data: bytes


@dataclass(slots=True)
class PostDraft:
    """A post being composed, between the upload step and publishing.

    Persisted (not just held in memory) for two reasons: the wizard is two
    requests apart (upload, then choose targets and publish), and Instagram's
    `/media` endpoint fetches its image from a public URL rather than taking
    bytes directly — the images have to survive at `public_media_url` for as
    long as Instagram takes to fetch them. `public_key` is what keeps that
    unauthenticated URL from being guessable (see the migration docstring).
    """

    MAX_IMAGES: ClassVar[int] = 10

    id: str
    caption: str
    public_key: str
    images: tuple[DraftImage, ...]
    created_at: datetime
    status: DraftStatus = DraftStatus.DRAFT
    error: str | None = None
    post_id: str | None = None
    published_at: datetime | None = None
    # What the wizard's targets step chose — set once, either by
    # submit_for_review() (queued) or by PublishDraft (published/failed
    # immediately). None only for a draft that never got past the upload step.
    targets: PublishTargets | None = None
    # "calendar:<event id>" when this draft was started from an event's "Post
    # erstellen"; None for a standalone post. Parsed by whoever links the
    # resulting post back (see PublishDraft, EventDirectory.link).
    event_ref: str | None = None

    @classmethod
    def new(
        cls,
        caption: str,
        images: Sequence[DraftImage],
        now: datetime,
        event_ref: str | None = None,
    ) -> PostDraft:
        return cls(
            id=uuid.uuid4().hex,
            caption=caption,
            public_key=secrets.token_urlsafe(32),
            images=tuple(images),
            created_at=now,
            event_ref=event_ref,
        )

    def public_media_url(self, base_url: str, index: int) -> str:
        return f"{base_url.rstrip('/')}/media/drafts/{self.id}/{index}?key={self.public_key}"

    def submit_for_review(self, targets: PublishTargets) -> None:
        """Queue this draft for a human to approve, with the targets it will publish to."""
        if self.status != DraftStatus.DRAFT:
            raise ValueError(f"cannot submit for review from {self.status}")
        self.targets = targets
        self.status = DraftStatus.REVIEW

    def is_reviewable(self) -> bool:
        """True when the Freigabe page can offer this draft: queued, or a retryable failure."""
        return self.status in {DraftStatus.REVIEW, DraftStatus.FAILED} and self.targets is not None

    def mark_published(self, post_id: str, now: datetime) -> None:
        self.status = DraftStatus.PUBLISHED
        self.post_id = post_id
        self.published_at = now
        self.error = None

    def mark_failed(self, error: str) -> None:
        self.status = DraftStatus.FAILED
        self.error = error[: Delivery.MAX_ERROR_LENGTH]


@dataclass(frozen=True, slots=True)
class PublishTargets:
    """What the wizard's publish step chose: Instagram, and/or a set of destinations."""

    instagram: bool
    destinations: tuple[Destination, ...]


# The one Instagram "channel": a single-account app publishes to exactly one
# place, so this fixed key stands in for both the channel_settings row (the
# auto-publish switch) and the Delivery recorded for a wizard post that went
# to Instagram — see publish_draft.py. Fixed rather than keyed by the
# connected account's external_user_id because the switch must exist (and be
# toggleable) before any token does.
INSTAGRAM_CHANNEL = Destination("instagram", "account")


@dataclass(frozen=True, slots=True)
class ChannelPolicy:
    """One channel's auto-publish setting, as stored in channel_settings."""

    destination: Destination
    auto_publish: bool


@dataclass(frozen=True, slots=True)
class ComposeHint:
    """What the calendar offers to prefill the compose wizard for one event.

    Mirrors calendar.domain.entities.ComposeHint the other way round — the
    same "each context has its own tiny read model of the other's entity"
    rule LinkedEvent already follows, via EventDirectory.compose_hint.
    """

    event_id: str
    title: str
    caption: str
    detail_url: str


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
    # The scope Instagram Login must grant before /media (publishing) works;
    # a token connected before this scope existed has an empty `scopes` and
    # needs a one-time re-connect (changing the requested scope string forces
    # that re-connect — see InstagramClient.SCOPES).
    PUBLISH_SCOPE: ClassVar[str] = "instagram_business_content_publish"

    source: str
    access_token: AccessToken
    external_user_id: str | None
    expires_at: datetime
    refreshed_at: datetime
    scopes: str = ""

    def needs_refresh(self, now: datetime) -> bool:
        return (
            now - self.refreshed_at >= timedelta(days=self.REFRESH_AFTER_DAYS)
            or self.expires_at - now <= timedelta(days=self.REFRESH_WITHIN_EXPIRY_DAYS)
        )

    @property
    def can_publish(self) -> bool:
        return self.PUBLISH_SCOPE in self.scopes.split(",")
