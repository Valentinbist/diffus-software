from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.application.overview import PostView
from diffus.crossposting.domain.entities import (
    Delivery,
    DeliveryStatus,
    Destination,
    MediaItem,
    MediaType,
    Post,
)
from diffus.crossposting.presentation.display import (
    delivery_label,
    sink_label,
    stored_cover,
    target_label,
)

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin (CEST)


def test_stored_cover_is_the_first_media_item_with_a_stored_still():
    post = Post(
        id="p",
        source="instagram",
        caption=None,
        permalink="https://instagram.com/p/p/",
        media=(
            MediaItem(url="https://cdn.example.com/0.mp4", type=MediaType.VIDEO),
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
        ),
        posted_at=NOW,
    )

    assert stored_cover(PostView(post=post, deliveries=[], stored_previews=frozenset({1}))) == 1
    assert stored_cover(PostView(post=post, deliveries=[], stored_previews=frozenset())) is None


def test_delivery_label_names_the_target_only_when_there_are_several():
    dest = Destination("telegram", "-100")
    sent = Delivery(post_id="p", destination=dest, status=DeliveryStatus.SENT)
    failed = Delivery(post_id="p", destination=dest, status=DeliveryStatus.FAILED)

    assert delivery_label(sent, multi_target=False) == "Telegram ✓"
    assert delivery_label(sent, multi_target=True) == "Telegram -100 ✓"
    assert delivery_label(failed, multi_target=False) == "Telegram ✕ nicht durchgekommen"


def test_sink_label_falls_back_to_capitalized_name_for_unknown_sinks():
    assert sink_label("telegram") == "Telegram"
    assert sink_label("signal") == "Signal"


def test_target_label_combines_sink_label_and_address():
    delivery = Delivery(post_id="p", destination=Destination("signal", "+49151"))

    assert target_label(delivery) == "Signal +49151"
