from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from connector.application.overview import PostView
from connector.domain.entities import Delivery, DeliveryStatus, MediaItem, MediaType, Post
from connector.presentation.display import (
    delivery_label,
    error_text,
    format_ago,
    format_day,
    format_when,
    stored_cover,
    summary,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin (CEST)


def test_when_today_yesterday_and_older():
    assert format_when(datetime(2026, 9, 3, 8, 22, tzinfo=UTC), NOW, TZ) == "Heute, 10:22"
    assert format_when(datetime(2026, 9, 2, 17, 3, tzinfo=UTC), NOW, TZ) == "Gestern, 19:03"
    assert format_when(datetime(2026, 8, 28, 9, 40, tzinfo=UTC), NOW, TZ) == "28. August, 11:40"


def test_when_adds_the_year_only_outside_the_current_one():
    assert format_when(datetime(2025, 12, 24, 11, 0, tzinfo=UTC), NOW, TZ) == (
        "24. Dezember 2025, 12:00"
    )


def test_day_boundary_follows_the_display_zone_not_utc():
    # 22:30 UTC on the 2nd is already 00:30 on the 3rd in Berlin.
    assert format_when(datetime(2026, 9, 2, 22, 30, tzinfo=UTC), NOW, TZ) == "Heute, 00:30"
    assert format_day(datetime(2026, 9, 2, 22, 30, tzinfo=UTC), NOW, TZ) == "Heute"


def test_ago_picks_the_largest_sensible_unit():
    assert format_ago(NOW - timedelta(seconds=30), NOW) == "gerade eben"
    assert format_ago(NOW - timedelta(minutes=1), NOW) == "vor 1 Minute"
    assert format_ago(NOW - timedelta(minutes=4), NOW) == "vor 4 Minuten"
    assert format_ago(NOW - timedelta(hours=2), NOW) == "vor 2 Stunden"
    assert format_ago(NOW - timedelta(days=3), NOW) == "vor 3 Tagen"
    assert format_ago(NOW + timedelta(minutes=5), NOW) == "gerade eben"  # clock skew, not future


def test_summary_takes_the_first_real_line_and_truncates():
    assert summary(None) == ""
    assert summary("  \nSiebdruck-Nachmittag! 🧵\n📅 5. September") == "Siebdruck-Nachmittag! 🧵"
    cut = summary("x" * 200, limit=90)
    assert len(cut) == 90
    assert cut.endswith("…")


def test_error_text_strips_tokens_from_quoted_urls():
    ig = "400 for url 'https://graph.instagram.com/me/media?fields=id&access_token=IGQVJ123'"
    tg = "401 for url 'https://api.telegram.org/bot123456:ABC-def_9/sendPhoto'"

    assert "IGQVJ123" not in error_text(ig)
    assert "access_token=…" in error_text(ig)
    assert "123456:ABC-def_9" not in error_text(tg)
    assert "/bot…/sendPhoto" in error_text(tg)


def test_stored_cover_is_the_first_media_item_with_a_stored_still():
    post = Post(
        id="p",
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


def test_delivery_label_names_the_chat_only_when_there_are_several():
    sent = Delivery(post_id="p", chat_id="-100", status=DeliveryStatus.SENT)
    failed = Delivery(post_id="p", chat_id="-100", status=DeliveryStatus.FAILED)

    assert delivery_label(sent, multi_chat=False) == "Telegram ✓"
    assert delivery_label(sent, multi_chat=True) == "Telegram -100 ✓"
    assert delivery_label(failed, multi_chat=False) == "Telegram ✕ nicht durchgekommen"
