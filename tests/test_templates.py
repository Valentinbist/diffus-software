"""The two pages, rendered straight from the Jinja env, in every state the mockups cover."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from connector.application.overview import Overview, PostView
from connector.domain.entities import Delivery, DeliveryStatus, MediaItem, MediaType, Post, Token
from connector.presentation.jobs import LastRun
from connector.presentation.routes import configure_templates, templates

configure_templates(ZoneInfo("Europe/Berlin"))

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin


def make_token(days_left: int = 40) -> Token:
    return Token(
        access_token="t",
        ig_user_id="1",
        expires_at=NOW + timedelta(days=days_left),
        refreshed_at=NOW,
    )


def make_post(
    caption: str | None = "Siebdruck-Nachmittag, offen für alle",
    cover: bool = True,
    extra_image: bool = False,
) -> Post:
    media = [
        MediaItem(
            url="https://cdn.example.com/p1.mp4",
            type=MediaType.VIDEO,
            thumbnail_url="https://cdn.example.com/p1-thumb.jpg" if cover else None,
        )
    ]
    if extra_image:
        media.append(MediaItem(url="https://cdn.example.com/p1-2.jpg", type=MediaType.IMAGE))
    return Post(
        id="p1",
        caption=caption,
        permalink="https://instagram.com/p/p1/",
        media=tuple(media),
        posted_at=NOW - timedelta(hours=2),
    )


def render_index(ov: Overview, last_run: LastRun | None = None, multi_chat: bool = False) -> str:
    return templates.env.get_template("index.html").render(
        ov=ov, now=NOW, last_run=last_run, multi_chat=multi_chat
    )


def render_post(view: PostView, multi_chat: bool = False) -> str:
    return templates.env.get_template("post.html").render(view=view, now=NOW, multi_chat=multi_chat)


def connected(*views: PostView) -> Overview:
    return Overview(token=make_token(), posts=list(views))


# -- overview -----------------------------------------------------------------


def test_not_connected_offers_to_connect():
    html = render_index(Overview(token=None, posts=[]))

    assert "Instagram verbinden" in html
    assert 'href="/oauth/login"' in html
    assert "Noch keine Posts" in html
    assert "Jetzt abgleichen" not in html


def test_connected_shows_the_last_sync_and_a_sync_button():
    html = render_index(connected(), last_run=LastRun(at=NOW - timedelta(minutes=4)))

    assert "Läuft. Letzter Abgleich vor 4 Minuten." in html
    assert "Jetzt abgleichen" in html
    assert "Neu verbinden" not in html


def test_failed_sync_and_expiring_token_are_called_out():
    html = render_index(
        Overview(token=make_token(days_left=3), posts=[]),
        last_run=LastRun(at=NOW - timedelta(minutes=1), sync_error="boom", refresh_error="nope"),
    )

    assert "ist fehlgeschlagen" in html
    assert "boom" in html
    assert "Token-Auffrischung fehlgeschlagen" in html
    assert "in 3 Tagen" in html
    assert "Neu verbinden" in html


def test_delivered_post_row_links_to_the_detail_page_with_the_stored_preview():
    sent = Delivery(post_id="p1", chat_id="c1", status=DeliveryStatus.SENT)
    view = PostView(post=make_post(), deliveries=[sent], stored_previews=frozenset({0}))

    html = render_index(connected(view))

    assert 'href="/posts/p1"' in html
    assert 'src="/posts/p1/media/0"' in html
    assert "cdn.example.com" not in html  # never hotlink when a stored copy exists
    assert "Siebdruck-Nachmittag, offen für alle" in html
    assert "Heute, 10:00 – Telegram ✓" in html
    assert "Nochmal senden" not in html


def test_row_without_a_stored_preview_falls_back_to_the_cdn_then_to_a_placeholder():
    cdn = render_index(connected(PostView(post=make_post(), deliveries=[])))
    none = render_index(connected(PostView(post=make_post(cover=False), deliveries=[])))

    assert 'src="https://cdn.example.com/p1-thumb.jpg"' in cdn
    assert ">Video<" in none  # no still frame anywhere: a labelled placeholder, not a broken image


def test_failed_delivery_offers_resend_and_hides_the_bot_token():
    failed = Delivery(
        post_id="p1",
        chat_id="c1",
        status=DeliveryStatus.FAILED,
        attempts=1,
        error="401 for url 'https://api.telegram.org/bot123:ABC/sendPhoto'",
    )

    html = render_index(connected(PostView(post=make_post(), deliveries=[failed])))

    assert "Telegram ✕ nicht durchgekommen" in html
    assert "Nochmal senden" in html
    assert 'name="chat_id" value="c1"' in html
    assert "bot123:ABC" not in html


def test_several_chats_get_one_label_each_in_chat_order():
    deliveries = [
        Delivery(post_id="p1", chat_id="c2", status=DeliveryStatus.SENT),
        Delivery(post_id="p1", chat_id="c1", status=DeliveryStatus.SKIPPED),
    ]

    html = render_index(
        connected(PostView(post=make_post(), deliveries=deliveries)), multi_chat=True
    )

    assert "Telegram c1 – übersprungen" in html
    assert "Telegram c2 ✓" in html
    assert html.index("Telegram c1") < html.index("Telegram c2")
    assert "Nochmal an c1 senden" in html


def test_caption_is_escaped_and_missing_caption_is_labelled():
    evil = render_index(
        connected(PostView(post=make_post(caption="<script>alert(1)</script>"), deliveries=[]))
    )
    empty = render_index(connected(PostView(post=make_post(caption=None), deliveries=[])))

    assert "<script>" not in evil
    assert "&lt;script&gt;" in evil
    assert "Ohne Text" in empty


# -- post detail --------------------------------------------------------------


def test_detail_page_shows_all_media_the_full_caption_and_delivery_details():
    sent = Delivery(
        post_id="p1",
        chat_id="c1",
        status=DeliveryStatus.SENT,
        attempts=1,
        sent_at=NOW - timedelta(hours=1),
    )
    view = PostView(
        post=make_post(caption="Siebdruck-Nachmittag!\n📅 5. September", extra_image=True),
        deliveries=[sent],
        stored_previews=frozenset({0}),
    )

    html = render_post(view)

    assert "« Alle Posts" in html
    assert 'src="/posts/p1/media/0"' in html  # stored copy
    assert 'src="https://cdn.example.com/p1-2.jpg"' in html  # not stored yet: CDN fallback
    assert "📅 5. September" in html
    assert "Auf Instagram öffnen" in html
    assert "Telegram ✓" in html
    assert "Zugestellt Heute, 11:00" in html
    assert "Nochmal senden" not in html


def test_detail_page_failed_delivery_shows_attempts_error_and_resends_back_here():
    failed = Delivery(
        post_id="p1", chat_id="c1", status=DeliveryStatus.FAILED, attempts=2, error="chat not found"
    )

    html = render_post(PostView(post=make_post(), deliveries=[failed]))

    assert "2 Versuche, zuletzt nicht durchgekommen" in html
    assert "chat not found" in html
    assert 'name="next" value="/posts/p1"' in html
    assert "Nochmal senden" in html


def test_detail_page_without_deliveries_says_so():
    html = render_post(PostView(post=make_post(caption=None), deliveries=[]))

    assert "Ohne Text" in html
    assert "Noch an keinen Kanal zugestellt." in html
