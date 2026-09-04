from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.application.channels import InstagramChannel
from diffus.crossposting.application.overview import PostView
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    Delivery,
    DeliveryStatus,
    Destination,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
)
from diffus.crossposting.presentation.display import (
    delivery_label,
    filter_by_events,
    filter_by_source,
    instagram_hint,
    sink_label,
    source_label,
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


def make_post_view(post_id: str, events: list[LinkedEvent] | None = None) -> PostView:
    post = Post(
        id=post_id,
        source="instagram",
        caption=None,
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=NOW,
    )
    return PostView(post=post, deliveries=[], events=events or [])


def test_filter_by_events_keeps_only_linked_or_only_unlinked_posts():
    event = LinkedEvent(id="e1", title="Plenum", starts_at=NOW, detail_url="/calendar/events/e1")
    linked = make_post_view("p1", events=[event])
    unlinked = make_post_view("p2")

    assert filter_by_events([linked, unlinked], "with") == [linked]
    assert filter_by_events([linked, unlinked], "without") == [unlinked]
    assert filter_by_events([linked, unlinked], "all") == [linked, unlinked]
    assert filter_by_events([linked, unlinked], "garbage") == [linked, unlinked]


def make_post_view_with_source(post_id: str, source: str) -> PostView:
    post = Post(
        id=post_id,
        source=source,
        caption=None,
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=NOW,
    )
    return PostView(post=post, deliveries=[])


def test_source_label_names_known_sources_and_falls_back_to_capitalized():
    assert source_label("instagram") == "Instagram"
    assert source_label("diffus") == "App"
    assert source_label("signal") == "Signal"


def test_filter_by_source_keeps_only_instagram_or_only_diffus_posts():
    ig = make_post_view_with_source("p1", "instagram")
    app = make_post_view_with_source("p2", "diffus")

    assert filter_by_source([ig, app], "instagram") == [ig]
    assert filter_by_source([ig, app], "diffus") == [app]
    assert filter_by_source([ig, app], "all") == [ig, app]
    assert filter_by_source([ig, app], "garbage") == [ig, app]


def test_delivery_label_for_a_review_row_says_freigabe_ausstehend():
    delivery = Delivery(
        post_id="p", destination=Destination("telegram", "c1"), status=DeliveryStatus.REVIEW
    )

    assert delivery_label(delivery, multi_target=False) == "Telegram · Freigabe ausstehend"
    assert delivery_label(delivery, multi_target=True) == "Telegram c1 · Freigabe ausstehend"


def test_delivery_label_for_instagram_never_names_the_address_even_multi_target():
    sent = Delivery(post_id="p", destination=INSTAGRAM_CHANNEL, status=DeliveryStatus.SENT)

    assert delivery_label(sent, multi_target=False) == "Instagram ✓"
    assert delivery_label(sent, multi_target=True) == "Instagram ✓"


def make_channel(
    connected: bool = True,
    can_publish: bool = True,
    public_https: bool = True,
) -> InstagramChannel:
    return InstagramChannel(
        destination=INSTAGRAM_CHANNEL,
        connected=connected,
        can_publish=can_publish,
        public_https=public_https,
        auto_publish=False,
    )


def test_instagram_hint_covers_all_four_states():
    assert instagram_hint(make_channel(connected=False)) == "Instagram ist nicht verbunden."
    assert (
        instagram_hint(make_channel(can_publish=False))
        == "Instagram neu verbinden, um Veröffentlichen freizuschalten."
    )
    assert instagram_hint(make_channel(public_https=False)) == (
        "PUBLIC_BASE_URL ist keine öffentliche https-Adresse – Instagram kann die Bilder "
        "nicht laden. Telegram geht trotzdem."
    )
    assert instagram_hint(make_channel()) is None
