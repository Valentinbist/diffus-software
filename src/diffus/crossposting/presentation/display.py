"""Formatting for the UI: German, human-scale, matching the Crossposting mockups.

Pure functions that take `now` explicitly so they are trivially testable. Wired
into Jinja as filters by presentation/routes.py.
"""

from __future__ import annotations

from diffus.crossposting.application.overview import PostView
from diffus.crossposting.domain.entities import Delivery, DeliveryStatus

# Sinks the connector knows how to label. A sink with no entry falls back to
# its name, capitalized, so a new adapter renders sanely before display.py
# is ever updated for it.
SINK_LABELS = {"telegram": "Telegram"}

# What a delivery row says after the sink/target label. The mockups use ✓ / ✕ and plain words.
STATUS_TEXT = {
    DeliveryStatus.SENT: "✓",
    DeliveryStatus.FAILED: "✕ nicht durchgekommen",
    DeliveryStatus.PENDING: "… wird gesendet",
    DeliveryStatus.SKIPPED: "– übersprungen",
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
    """'Telegram ✓', or 'Telegram <address> ✓' when more than one target is configured."""
    target = target_label(delivery) if multi_target else sink_label(delivery.destination.sink)
    return f"{target} {STATUS_TEXT[delivery.status]}"
