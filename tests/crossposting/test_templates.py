"""The two pages, rendered straight from the Jinja env, in every state the mockups cover."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.crossposting.application.channels import Channels, InstagramChannel, TelegramChannel
from diffus.crossposting.application.overview import Overview, PostView
from diffus.crossposting.application.review import DraftReview, PostReview, ReviewQueue
from diffus.crossposting.application.sync_job import LastRun
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    AccessToken,
    ComposeHint,
    Delivery,
    DeliveryStatus,
    Destination,
    DraftImage,
    DraftStatus,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    PublishTargets,
    Token,
)
from diffus.crossposting.presentation import display
from diffus.crossposting.presentation.routes import build_templates

templates = build_templates(ZoneInfo("Europe/Berlin"))

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin
C1 = Destination("telegram", "c1")


def make_channels(
    instagram_connected: bool = True,
    instagram_can_publish: bool = True,
    instagram_public_https: bool = True,
    instagram_auto: bool = False,
    telegram: tuple[TelegramChannel, ...] = (
        TelegramChannel(destination=C1, label="Telegram", auto_publish=False),
    ),
) -> Channels:
    return Channels(
        instagram=InstagramChannel(
            destination=INSTAGRAM_CHANNEL,
            connected=instagram_connected,
            can_publish=instagram_can_publish,
            public_https=instagram_public_https,
            auto_publish=instagram_auto,
        ),
        telegram=telegram,
    )


def make_token(days_left: int = 40, can_publish: bool = True) -> Token:
    return Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=NOW + timedelta(days=days_left),
        refreshed_at=NOW,
        scopes=Token.PUBLISH_SCOPE if can_publish else "",
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
        source="instagram",
        caption=caption,
        permalink="https://instagram.com/p/p1/",
        media=tuple(media),
        posted_at=NOW - timedelta(hours=2),
    )


def render_index(
    ov: Overview,
    last_run: LastRun | None = None,
    multi_target: bool = False,
    events: str = "all",
    source: str = "all",
    channels: Channels | None = None,
    review_count: int = 0,
) -> str:
    return templates.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=last_run,
        multi_target=multi_target,
        events=events,
        event_pills=display.EVENT_PILLS,
        source=source,
        source_pills=display.SOURCE_PILLS,
        channels=channels or make_channels(),
        review_count=review_count,
    )


def render_post(view: PostView, multi_target: bool = False) -> str:
    return templates.env.get_template("post.html").render(
        view=view, now=NOW, multi_target=multi_target
    )


def render_review(
    queue: ReviewQueue, channels: Channels | None = None, error: str | None = None
) -> str:
    return templates.env.get_template("review.html").render(
        queue=queue, channels=channels or make_channels(), now=NOW, multi_target=False, error=error
    )


def render_compose(
    caption: str = "",
    hint: ComposeHint | None = None,
    event: str = "",
    channels: Channels | None = None,
    error: str | None = None,
    cancel_url: str = "/",
) -> str:
    return templates.env.get_template("compose.html").render(
        caption=caption,
        hint=hint,
        event=event,
        channels=channels or make_channels(),
        error=error,
        now=NOW,
        cancel_url=cancel_url,
    )


def make_draft(caption: str = "Hallo") -> PostDraft:
    return PostDraft.new(
        caption=caption, images=[DraftImage("image/jpeg", 1, 1, b"x")], now=NOW
    )


def render_compose_preview(
    draft: PostDraft | None = None,
    hint: ComposeHint | None = None,
    channels: Channels | None = None,
    instagram: bool = False,
    telegram: list[str] | None = None,
    all_auto: bool = False,
    error: str | None = None,
) -> str:
    draft = draft or make_draft()
    return templates.env.get_template("compose_preview.html").render(
        draft=draft,
        image_urls=tuple(f"/drafts/{draft.id}/media/{i}" for i in range(len(draft.images))),
        hint=hint,
        channels=channels or make_channels(),
        instagram=instagram,
        telegram=telegram or [],
        all_auto=all_auto,
        error=error,
        now=NOW,
    )


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


def test_connected_without_publish_scope_shows_the_reconnect_hint():
    html = render_index(Overview(token=make_token(can_publish=False), posts=[]))

    assert "Instagram neu verbinden, um Veröffentlichen freizuschalten." in html
    assert "Neu verbinden" in html


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
    sent = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.SENT
    )
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
        destination=Destination("telegram", "c1"),
        status=DeliveryStatus.FAILED,
        attempts=1,
        error="401 for url 'https://api.telegram.org/bot123:ABC/sendPhoto'",
    )

    html = render_index(connected(PostView(post=make_post(), deliveries=[failed])))

    assert "Telegram ✕ nicht durchgekommen" in html
    assert "Nochmal senden" in html
    assert 'name="destination" value="telegram:c1"' in html
    assert "bot123:ABC" not in html


def test_several_destinations_get_one_label_each_in_destination_order():
    deliveries = [
        Delivery(
            post_id="p1", destination=Destination("telegram", "c2"), status=DeliveryStatus.SENT
        ),
        Delivery(
            post_id="p1",
            destination=Destination("telegram", "c1"),
            status=DeliveryStatus.SKIPPED,
        ),
    ]

    html = render_index(
        connected(PostView(post=make_post(), deliveries=deliveries)), multi_target=True
    )

    assert "Telegram c1 – übersprungen" in html
    assert "Telegram c2 ✓" in html
    assert html.index("Telegram c1") < html.index("Telegram c2")
    assert "Nochmal an Telegram c1 senden" in html


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
        destination=Destination("telegram", "c1"),
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
        post_id="p1",
        destination=Destination("telegram", "c1"),
        status=DeliveryStatus.FAILED,
        attempts=2,
        error="chat not found",
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


# -- nav + header + modal --------------------------------------------------------


def test_nav_shows_the_calendar_link_only_when_the_calendar_context_is_enabled():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_calendar = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="all",
        event_pills=display.EVENT_PILLS,
        source="all",
        source_pills=display.SOURCE_PILLS,
        channels=make_channels(),
        review_count=0,
    )
    without_calendar = render_index(ov)

    assert 'href="/calendar"' in with_calendar
    assert 'href="/calendar"' not in without_calendar


def test_base_layout_has_the_topbar_brand_and_modal_dialog():
    html = render_index(Overview(token=None, posts=[]))

    assert 'class="topbar"' in html
    assert ">diffus.space<" in html
    assert '<dialog id="modal"' in html
    assert '<div class="page">' in html
    assert 'href="/static/dist/' in html


def test_thumb_and_title_links_open_in_the_modal():
    view = PostView(post=make_post(), deliveries=[])

    html = render_index(connected(view))

    assert html.count("data-modal") >= 2


def test_post_detail_kicker_back_link_is_hidden_inside_the_modal():
    html = render_post(PostView(post=make_post(), deliveries=[]))

    assert '<a class="plain back" href="/">« Alle Posts</a>' in html


# -- event filter pills and linked events ----------------------------------------


def test_event_pills_show_only_when_the_calendar_context_is_enabled():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_calendar = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="with",
        event_pills=display.EVENT_PILLS,
        source="all",
        source_pills=display.SOURCE_PILLS,
        channels=make_channels(),
        review_count=0,
    )

    assert '<span class="pill current">Mit Termin</span>' in with_calendar
    assert 'href="/?source=all&events=without"' in with_calendar
    assert 'href="/?source=all&events=with"' not in render_index(ov)  # disabled: no pills at all


def test_index_row_lists_linked_events_and_marks_a_removed_one():
    event = LinkedEvent(id="e1", title="Plenum", starts_at=NOW, detail_url="/calendar/events/e1")
    removed = LinkedEvent(
        id="e2", title="Alte Reihe", starts_at=NOW, detail_url="/calendar/events/e2", removed=True
    )
    view = PostView(post=make_post(), deliveries=[], events=[event, removed])

    html = render_index(connected(view))

    assert 'href="/calendar/events/e1" data-modal>Plenum, Heute</a>' in html
    assert "Alte Reihe, Heute</a> (gelöscht)" in html


def test_post_detail_termine_section_and_link_button_only_when_calendar_enabled():
    event = LinkedEvent(id="e1", title="Plenum", starts_at=NOW, detail_url="/calendar/events/e1")
    linked_view = PostView(post=make_post(), deliveries=[], events=[event])
    empty_view = PostView(post=make_post(), deliveries=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_event = enabled.env.get_template("post.html").render(
        view=linked_view, now=NOW, multi_target=False
    )
    without_event = enabled.env.get_template("post.html").render(
        view=empty_view, now=NOW, multi_target=False
    )
    disabled = render_post(empty_view)

    assert "Termine" in with_event
    assert "Plenum, Heute" in with_event
    assert 'href="/calendar/link?post=p1" data-modal>Mit Termin verknüpfen</a>' in with_event
    assert "Mit keinem Termin verknüpft." in without_event
    assert "Mit Termin verknüpfen" not in disabled


# -- Social Posts: rename, source pill, Freigabe notice, Kanäle form --------------


def test_social_posts_h1_and_kicker():
    html = render_index(Overview(token=None, posts=[]))

    assert "<h1 class=\"h1\">Social Posts</h1>" in html
    assert "Instagram · Telegram · App" in html


def test_index_row_shows_a_source_pill_before_the_caption():
    view = PostView(post=make_post(), deliveries=[])

    html = render_index(connected(view))

    assert '<span class="source">Instagram</span>' in html


def test_review_delivery_shows_freigabe_ausstehend_and_no_resend_button():
    review = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.REVIEW
    )

    html = render_index(connected(PostView(post=make_post(), deliveries=[review])))

    assert "Telegram · Freigabe ausstehend" in html
    assert "Nochmal senden" not in html


def test_review_notice_shows_only_when_the_count_is_positive():
    zero = render_index(Overview(token=None, posts=[]), review_count=0)
    one = render_index(Overview(token=None, posts=[]), review_count=1)
    three = render_index(Overview(token=None, posts=[]), review_count=3)

    assert "wartet auf Freigabe" not in zero
    assert "warten auf Freigabe" not in zero
    assert "1 Post wartet auf Freigabe." in one
    assert "3 Posts warten auf Freigabe." in three


def test_kanaele_form_checkbox_uses_the_destination_text_form():
    channels = make_channels(
        telegram=(TelegramChannel(destination=C1, label="Telegram", auto_publish=True),)
    )

    html = render_index(Overview(token=None, posts=[]), channels=channels)

    assert 'name="auto" value="telegram:c1" checked' in html
    assert "Ohne Haken wartet ein Post für diesen Kanal auf Freigabe." in html


def test_kanaele_form_shows_the_instagram_hint_when_not_ready():
    channels = make_channels(instagram_connected=False)

    html = render_index(Overview(token=None, posts=[]), channels=channels)

    assert "Instagram ist nicht verbunden." in html


def test_post_erstellen_button_opens_the_compose_wizard_in_a_modal():
    html = render_index(Overview(token=None, posts=[]))

    assert 'href="/posts/new" data-modal>Post erstellen</a>' in html


# -- post detail: Freigabe + Instagram delivery + SKIPPED wording ----------------


def test_post_detail_review_delivery_waits_for_freigabe_without_a_resend_button():
    review = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.REVIEW
    )

    html = render_post(PostView(post=make_post(), deliveries=[review]))

    assert "Wartet auf Freigabe" in html
    assert "Nochmal senden" not in html


def test_post_detail_shows_instagram_delivery_as_a_check():
    sent = Delivery(post_id="p1", destination=INSTAGRAM_CHANNEL, status=DeliveryStatus.SENT)

    html = render_post(PostView(post=make_post(), deliveries=[sent]))

    assert "Instagram ✓" in html


def test_post_detail_skipped_delivery_reads_nicht_gesendet():
    skipped = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.SKIPPED
    )

    html = render_post(PostView(post=make_post(), deliveries=[skipped]))

    assert "Nicht gesendet." in html


# -- Freigabe page ------------------------------------------------------------------


def test_review_page_empty_state():
    html = render_review(ReviewQueue(drafts=[], posts=[]))

    assert "Nichts wartet auf Freigabe." in html


def test_review_page_draft_block_shows_hint_targets_and_a_failed_error():
    draft = PostDraft.new(
        caption="Hallo Welt",
        images=[DraftImage("image/jpeg", 1, 1, b"x")],
        now=NOW,
        event_ref="calendar:e1",
    )
    draft.status = DraftStatus.FAILED
    draft.error = "Instagram meldet einen Fehler"
    draft.targets = PublishTargets(instagram=False, destinations=(C1,))
    hint = ComposeHint(event_id="e1", title="Plenum", caption="x", detail_url="/calendar/events/e1")
    review = DraftReview(draft=draft, image_urls=(f"/drafts/{draft.id}/media/0",), hint=hint)

    html = render_review(ReviewQueue(drafts=[review], posts=[]))

    assert "Hallo Welt" in html
    assert "Für Termin:" in html
    assert 'href="/calendar/events/e1" data-modal>Plenum</a>' in html
    assert "Instagram meldet einen Fehler" in html
    assert f'action="/freigabe/drafts/{draft.id}/approve"' in html
    assert f'action="/freigabe/drafts/{draft.id}/reject"' in html
    assert 'name="telegram" value="c1" checked' in html


def test_review_page_post_block_lists_proposed_destinations():
    view = PostView(post=make_post(), deliveries=[])
    review = PostReview(view=view, proposed=[C1])

    html = render_review(ReviewQueue(drafts=[], posts=[review]))

    assert f'action="/freigabe/posts/{view.post.id}/approve"' in html
    assert f'action="/freigabe/posts/{view.post.id}/reject"' in html
    assert 'name="telegram" value="c1" checked' in html


# -- compose wizard templates --------------------------------------------------------


def test_compose_form_prefills_the_caption_and_tags_each_channel():
    channels = make_channels(
        telegram=(TelegramChannel(destination=C1, label="Telegram", auto_publish=True),)
    )

    html = render_compose(caption="Vorbefüllter Text", channels=channels)

    assert "Vorbefüllter Text" in html
    assert "automatisch" in html


def test_compose_form_disables_instagram_and_shows_the_hint_when_not_ready():
    channels = make_channels(instagram_connected=False)

    html = render_compose(channels=channels)

    assert 'name="instagram"' in html
    assert "disabled" in html
    assert "Instagram ist nicht verbunden." in html


def test_compose_preview_button_label_depends_on_all_auto():
    published = render_compose_preview(all_auto=True)
    queued = render_compose_preview(all_auto=False)

    assert "Veröffentlichen" in published
    assert "Zur Freigabe" not in published
    assert "Zur Freigabe" in queued
    assert "Veröffentlichen" not in queued


# -- base.html: nav badge + Termin link ------------------------------------------


def test_base_layout_has_the_freigabe_badge_htmx_attributes():
    html = render_index(Overview(token=None, posts=[]))

    assert 'hx-get="/freigabe/count"' in html
    assert 'hx-trigger="load"' in html
    assert "Social Posts" in html


def test_termin_link_shows_only_when_the_calendar_context_is_enabled():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_calendar = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="all",
        event_pills=display.EVENT_PILLS,
        source="all",
        source_pills=display.SOURCE_PILLS,
        channels=make_channels(),
        review_count=0,
    )
    without_calendar = render_index(ov)

    assert "+ Termin" in with_calendar
    assert "+ Termin" not in without_calendar
