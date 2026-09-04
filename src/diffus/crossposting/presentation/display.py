"""Formatting for the UI: German, human-scale, matching the Crossposting mockups.

Pure functions that take `now` explicitly so they are trivially testable. Wired
into Jinja as filters by presentation/routes.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from diffus.crossposting.application.channels import InstagramChannel
from diffus.crossposting.application.overview import PostView
from diffus.crossposting.domain.entities import Delivery, DeliveryStatus

# Sinks the connector knows how to label. A sink with no entry falls back to
# its name, capitalized, so a new adapter renders sanely before display.py
# is ever updated for it.
SINK_LABELS = {"telegram": "Telegram", "instagram": "Instagram"}

EVENT_PILLS = (("all", "Alle"), ("with", "Mit Termin"), ("without", "Ohne Termin"))

# A post's origin: Instagram (polled) or the app's own wizard (source="diffus").
SOURCE_LABELS = {"instagram": "Instagram", "diffus": "App"}
SOURCE_PILLS = (("all", "Alle"), ("instagram", "Instagram"), ("diffus", "App"))


def source_label(source: str) -> str:
    """'Instagram' / 'App' for a known source, otherwise the name capitalized."""
    return SOURCE_LABELS.get(source, source.capitalize())


def filter_by_events(views: Sequence[PostView], mode: str) -> list[PostView]:
    """Keep posts with ('with') or without ('without') a linked event; anything else keeps all."""
    if mode == "with":
        return [v for v in views if v.events]
    if mode == "without":
        return [v for v in views if not v.events]
    return list(views)


def filter_by_source(views: Sequence[PostView], mode: str) -> list[PostView]:
    """Keep posts whose source is 'instagram' or 'diffus'; anything else keeps all."""
    if mode in SOURCE_LABELS:
        return [v for v in views if v.post.source == mode]
    return list(views)

# What a delivery row says after the sink/target label. The mockups use ✓ / ✕ and plain words.
STATUS_TEXT = {
    DeliveryStatus.SENT: "✓",
    DeliveryStatus.FAILED: "✕ nicht durchgekommen",
    DeliveryStatus.PENDING: "… wird gesendet",
    DeliveryStatus.SKIPPED: "– übersprungen",
    DeliveryStatus.REVIEW: "· Freigabe ausstehend",
}


def stored_cover(view: PostView) -> int | None:
    """Index of the first media item the connector holds a still image for."""
    return next((i for i in range(len(view.post.media)) if i in view.stored_previews), None)


def sink_label(sink: str) -> str:
    """'Telegram' for a known sink, otherwise the name capitalized."""
    return SINK_LABELS.get(sink, sink.capitalize())


def target_label(delivery: Delivery) -> str:
    """'Telegram -100...' — the sink label plus the address it went to."""
    return f"{sink_label(delivery.destination.sink)} {delivery.destination.address}"


def delivery_label(delivery: Delivery, multi_target: bool) -> str:
    """'Telegram ✓', or 'Telegram <address> ✓' when more than one target is configured.

    The Instagram sink is always the bare label ("Instagram ✓"), even when
    multi_target: there is only ever one Instagram channel (INSTAGRAM_CHANNEL,
    the fixed "account" address), so naming the address would just repeat it.
    """
    if multi_target and delivery.destination.sink != "instagram":
        target = target_label(delivery)
    else:
        target = sink_label(delivery.destination.sink)
    return f"{target} {STATUS_TEXT[delivery.status]}"


def instagram_hint(ch: InstagramChannel) -> str | None:
    """Why the Instagram checkbox on the compose form is disabled, or None when it isn't."""
    if not ch.connected:
        return "Instagram ist nicht verbunden."
    if not ch.can_publish:
        return "Instagram neu verbinden, um Veröffentlichen freizuschalten."
    if not ch.public_https:
        return (
            "PUBLIC_BASE_URL ist keine öffentliche https-Adresse – Instagram kann die Bilder "
            "nicht laden. Telegram geht trotzdem."
        )
    return None
