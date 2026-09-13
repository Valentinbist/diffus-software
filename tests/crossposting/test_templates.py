"""The two pages, rendered straight from the Jinja env, in every state the mockups cover."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from diffus.crossposting.application.activity import Activity
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
    NewEventRequest,
    Post,
    PostDraft,
    PublishTargets,
    ReviewLogEntry,
    ReviewOutcome,
    SubCalendarOption,
    Token,
)
from diffus.crossposting.domain.stats import ReviewStats
from diffus.crossposting.presentation import display
from diffus.crossposting.presentation.routes import build_templates
from diffus.shared.automation import Automation, JobRun, JobStatus, Streak
from diffus.shared.presentation.display import EMPTY_LINES

templates = build_templates(ZoneInfo("Europe/Berlin"))
# wizard_event.html (step 1) only ever renders with the calendar on — /neu
# redirects away otherwise — so its own tests use this one instead of the
# bare `templates` above (calendar_enabled=False).
templates_enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin
NO_STREAK = Streak()
C1 = Destination("telegram", "c1")
SUB_CALENDAR_OPTION = SubCalendarOption(
    id=5298948, name="Öffentliche Veranstaltung", color="#9BBB59"
)


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
    source: str = "instagram",
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
        source=source,
        caption=caption,
        permalink="https://instagram.com/p/p1/",
        media=tuple(media),
        posted_at=NOW - timedelta(hours=2),
    )


EMPTY_ACTIVITY = Activity(total=0, posted_at=())
EMPTY_STATS = ReviewStats(
    decisions=0,
    decided_today=0,
    empty_since=None,
    longest_empty=None,
    mean_reaction=None,
    fastest_reaction=None,
    reactions=0,
)


def render_index(
    ov: Overview,
    last_run: LastRun | None = None,
    multi_target: bool = False,
    events: str = "all",
    source: str = "all",
    channels: Channels | None = None,
    review_count: int = 0,
    now: datetime = NOW,
    activity: Activity = EMPTY_ACTIVITY,
    milestone: int | None = None,
) -> str:
    return templates.env.get_template("index.html").render(
        ov=ov,
        now=now,
        last_run=last_run,
        multi_target=multi_target,
        events=events,
        event_options=display.EVENT_OPTIONS,
        source=source,
        source_options=display.SOURCE_OPTIONS,
        channels=channels or make_channels(),
        review_count=review_count,
        activity=activity,
        milestone=milestone,
    )


def render_post(view: PostView, multi_target: bool = False) -> str:
    return templates.env.get_template("post.html").render(
        view=view, now=NOW, multi_target=multi_target
    )


def render_review(
    queue: ReviewQueue,
    channels: Channels | None = None,
    error: str | None = None,
    history: tuple[ReviewLogEntry, ...] = (),
    multi_target: bool = False,
    stats: ReviewStats = EMPTY_STATS,
    inbox_zero: str | None = None,
    reaction: str | None = None,
    milestone: int | None = None,
) -> str:
    return templates.env.get_template("review.html").render(
        queue=queue,
        channels=channels or make_channels(),
        now=NOW,
        multi_target=multi_target,
        error=error,
        history=history,
        stats=stats,
        inbox_zero=inbox_zero,
        reaction=reaction,
        milestone=milestone,
    )


def make_job_status(
    key: str = "posts",
    label: str = "Instagram-Abgleich",
    runs: tuple[JobRun, ...] = (),
    sync_action: str = "/sync",
    streak: Streak = NO_STREAK,
) -> JobStatus:
    return JobStatus(key=key, label=label, runs=runs, sync_action=sync_action, streak=streak)


def render_settings(
    ov: Overview,
    last_run: LastRun | None = None,
    channels: Channels | None = None,
    jobs: tuple[JobStatus, ...] = (),
    next_run: datetime | None = None,
    interval_minutes: int = 5,
) -> str:
    automation = Automation(
        interval_minutes=interval_minutes, jobs=lambda: jobs, next_run=lambda: next_run
    )
    return templates.env.get_template("settings.html").render(
        ov=ov,
        now=NOW,
        last_run=last_run,
        channels=channels or make_channels(),
        automation=automation,
        jobs=jobs,
        next_run=next_run,
    )


def render_compose(
    caption: str = "",
    hint: ComposeHint | None = None,
    event: str = "",
    channels: Channels | None = None,
    error: str | None = None,
    cancel_url: str = "/",
    enabled: bool = False,
) -> str:
    env = templates_enabled if enabled else templates
    return env.env.get_template("compose.html").render(
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
    enabled: bool = False,
) -> str:
    draft = draft or make_draft()
    env = templates_enabled if enabled else templates
    return env.env.get_template("compose_preview.html").render(
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


def make_prefill(
    title: str = "Fest",
    day: date = date(2026, 9, 12),
    start: time = time(18, 0),
    end: time = time(22, 0),
    whole_day: bool = False,
    description: str = "Text",
    location: str = "Ort",
    who: str = "Jona",
    sub_calendar_ids: frozenset[int] = frozenset({SUB_CALENDAR_OPTION.id}),
) -> NewEventRequest:
    return NewEventRequest(
        title=title,
        day=day,
        start=start,
        end=end,
        whole_day=whole_day,
        description=description,
        location=location,
        who=who,
        sub_calendar_ids=sub_calendar_ids,
    )


def render_wizard_event(
    prefill: NewEventRequest | None = None,
    sub_calendars: tuple[SubCalendarOption, ...] = (SUB_CALENDAR_OPTION,),
    post_id: str | None = None,
    view: PostView | None = None,
    error: str | None = None,
    enabled: bool = True,
) -> str:
    env = templates_enabled if enabled else templates
    return env.env.get_template("wizard_event.html").render(
        prefill=prefill or make_prefill(),
        sub_calendars=sub_calendars,
        post_id=post_id,
        view=view,
        error=error,
        now=NOW,
    )


def connected(*views: PostView) -> Overview:
    return Overview(token=make_token(), posts=list(views))


# -- overview -----------------------------------------------------------------


def test_not_connected_shows_an_attention_line_pointing_to_setup():
    html = render_index(Overview(token=None, posts=[]))

    assert "Instagram ist nicht verbunden" in html
    assert 'href="/einstellungen">Einstellungen</a>' in html
    assert "Noch keine Posts" in html
    assert "Jetzt abgleichen" not in html
    assert "Instagram verbinden" not in html


def test_connected_shows_no_status_line_and_no_attention_when_all_is_well():
    html = render_index(connected(), last_run=LastRun(at=NOW - timedelta(minutes=4)))

    assert "Letzter Abgleich" not in html
    assert "Läuft." not in html
    assert 'class="meta attention"' not in html
    assert "Jetzt abgleichen" not in html
    assert "Neu verbinden" not in html


def test_connected_without_publish_scope_shows_the_attention_line():
    html = render_index(Overview(token=make_token(can_publish=False), posts=[]))

    assert "Instagram neu verbinden, um Veröffentlichen freizuschalten" in html
    assert 'href="/einstellungen">Einstellungen</a>' in html
    assert "Neu verbinden" not in html


def test_failed_sync_is_called_out():
    html = render_index(
        Overview(token=make_token(days_left=40), posts=[]),
        last_run=LastRun(at=NOW - timedelta(minutes=1), sync_error="boom"),
    )

    assert "Der letzte Abgleich ist fehlgeschlagen" in html
    assert 'href="/einstellungen">Einstellungen</a>' in html
    assert "Letzter Abgleich" not in html  # the status line itself moved to /einstellungen


def test_refresh_failure_shows_the_attention_line():
    html = render_index(
        Overview(token=make_token(days_left=40), posts=[]),
        last_run=LastRun(at=NOW - timedelta(minutes=1), refresh_error="nope"),
    )

    assert "Token-Auffrischung fehlgeschlagen" in html
    assert 'href="/einstellungen">Einstellungen</a>' in html


def test_expiring_token_shows_the_attention_line():
    html = render_index(Overview(token=make_token(days_left=3), posts=[]))

    assert "in 3 Tagen" in html
    assert 'href="/einstellungen">Einstellungen</a>' in html


def test_only_one_attention_line_shows_when_several_conditions_apply():
    html = render_index(
        Overview(token=make_token(days_left=3), posts=[]),
        last_run=LastRun(at=NOW - timedelta(minutes=1), refresh_error="nope"),
    )

    assert html.count('→ <a href="/einstellungen">Einstellungen</a></p>') == 1
    assert "Token-Auffrischung fehlgeschlagen" in html
    assert "in 3 Tagen" not in html


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
    assert "Heute, 10:00" in html
    assert "Telegram ✓" in html
    assert "Nochmal senden" not in html


def test_index_row_shows_the_instagram_origin_line_linking_to_the_permalink():
    html = render_index(connected(PostView(post=make_post(), deliveries=[])))

    assert (
        'href="https://instagram.com/p/p1/" target="_blank" rel="noopener">Instagram ✓</a>'
        in html
    )


def test_index_row_has_no_instagram_origin_line_for_an_app_post():
    html = render_index(connected(PostView(post=make_post(source="diffus"), deliveries=[])))

    assert "Instagram ✓" not in html


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

    assert "<script>alert" not in evil  # base.html carries its own tiny inline script
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


def test_post_detail_renames_the_zustellung_eyebrow_to_kanaele():
    html = render_post(PostView(post=make_post(), deliveries=[]))

    assert "Kanäle" in html
    assert "Zustellung" not in html


def test_post_detail_shows_the_instagram_origin_line_only_for_an_instagram_post():
    ig_html = render_post(PostView(post=make_post(), deliveries=[]))
    app_html = render_post(PostView(post=make_post(source="diffus"), deliveries=[]))

    assert "Instagram ✓ · " in ig_html
    assert "Auf Instagram öffnen" in ig_html
    assert "Instagram ✓ · " not in app_html


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
        event_options=display.EVENT_OPTIONS,
        source="all",
        source_options=display.SOURCE_OPTIONS,
        channels=make_channels(),
        review_count=0,
        activity=EMPTY_ACTIVITY,
        milestone=None,
    )
    without_calendar = render_index(ov)

    assert 'href="/calendar"' in with_calendar
    assert 'href="/calendar"' not in without_calendar


def test_base_layout_has_the_sidebar_brand_and_modal_dialog():
    html = render_index(Overview(token=None, posts=[]))

    assert '<aside class="side">' in html
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


def test_termin_filter_shows_only_when_the_calendar_context_is_enabled():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_calendar = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="with",
        event_options=display.EVENT_OPTIONS,
        source="all",
        source_options=display.SOURCE_OPTIONS,
        channels=make_channels(),
        review_count=0,
        activity=EMPTY_ACTIVITY,
        milestone=None,
    )
    without_calendar = render_index(ov)

    assert '<option value="with" selected>Mit Termin</option>' in with_calendar
    assert '<option value="without">Ohne Termin</option>' in with_calendar
    assert 'name="events"' not in without_calendar  # disabled: no Termin filter at all


def test_filters_are_one_labelled_form_that_submits_itself():
    html = render_index(Overview(token=None, posts=[]), source="diffus")

    assert html.count('<form class="filters" method="get" action="/" data-autosubmit>') == 1
    assert "<label>Herkunft" in html
    assert '<select name="source">' in html
    assert '<option value="diffus" selected>App</option>' in html
    # The button is only for browsers without JS; base.html marks <html class="js">.
    assert '<button type="submit" class="btn nojs">Anwenden</button>' in html
    assert 'classList.add("js")' in html


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


def test_social_posts_h1_without_a_kicker():
    html = render_index(Overview(token=None, posts=[]))

    assert "<h1 class=\"h1\">Social Posts</h1>" in html
    assert "Instagram · Telegram · App" not in html  # round 6: the owner asked for it to go


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


# -- fun layer: greeting, milestone, heatmap -------------------------------------


def test_index_shows_the_greeting_kicker_in_the_morning_only():
    morning = datetime(2026, 9, 3, 5, 0, tzinfo=UTC)  # 07:00 Berlin
    afternoon = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)  # 14:00 Berlin

    with_greeting = render_index(Overview(token=None, posts=[]), now=morning)
    without_greeting = render_index(Overview(token=None, posts=[]), now=afternoon)

    assert "Guten Morgen." in with_greeting
    assert "Guten Morgen." not in without_greeting
    assert "Nachtschicht?" not in without_greeting


def test_index_milestone_line_appears_directly_under_the_h1():
    html = render_index(Overview(token=None, posts=[]), milestone=100)
    without = render_index(Overview(token=None, posts=[]), milestone=None)

    assert "Das war Post Nummer 100." in html
    assert "Das war Post Nummer" not in without


def test_index_heatmap_section_has_16_weeks_of_7_cells_and_marks_future_days():
    html = render_index(Overview(token=None, posts=[]))

    assert html.count('<div class="week">') == 16
    assert html.count('<span class="cell') == 112
    assert "future" in html  # the current week's remaining days


def test_index_heatmap_shows_the_total_and_busiest_day():
    activity = Activity(
        total=3,
        posted_at=(
            NOW - timedelta(days=1),
            NOW - timedelta(days=1),
            NOW - timedelta(days=2),
        ),
    )

    html = render_index(Overview(token=None, posts=[]), activity=activity)

    assert "3 Posts" in html
    assert "meiste an einem Tag: 2" in html


def test_index_no_longer_shows_the_kanaele_switches():
    html = render_index(Overview(token=None, posts=[]))

    assert 'name="auto"' not in html
    assert "Ohne Haken wartet ein Post für diesen Kanal auf Freigabe." not in html


def test_header_cta_is_the_only_neu_entry_point():
    html = render_index(Overview(token=None, posts=[]))

    assert 'href="/neu" data-modal>Neuer Post</a>' in html
    assert "+ Neu" not in html
    assert ">Neu<" not in html  # no bare "Neu" button left in the page body


def test_header_cta_says_neues_event_erstellen_with_the_calendar():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    html = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="all",
        event_options=display.EVENT_OPTIONS,
        source="all",
        source_options=display.SOURCE_OPTIONS,
        channels=make_channels(),
        review_count=0,
        activity=EMPTY_ACTIVITY,
        milestone=None,
    )

    assert 'href="/neu" data-modal>Neues Event erstellen</a>' in html
    assert 'href="/einstellungen"' in html


# -- settings page (replaces setup.html, round 5) ------------------------------


def test_settings_page_has_the_automatik_instagram_and_channels_sections():
    html = render_settings(Overview(token=None, posts=[]))

    assert '<h1 class="h1">Einstellungen</h1>' in html
    assert '<p class="eyebrow">Automatik</p>' in html
    assert '<p class="eyebrow">Instagram</p>' in html
    assert '<p class="eyebrow">Automatisch veröffentlichen</p>' in html


def test_settings_page_kanaele_form_checkbox_uses_the_destination_text_form():
    channels = make_channels(
        telegram=(TelegramChannel(destination=C1, label="Telegram", auto_publish=True),)
    )

    html = render_settings(Overview(token=None, posts=[]), channels=channels)

    assert 'name="auto" value="telegram:c1" checked' in html
    assert 'action="/channels"' in html
    assert "Ohne Haken wartet ein Post für diesen Kanal auf Freigabe." in html
    assert "– automatisch veröffentlichen" not in html  # suffix dropped (round 5)


def test_settings_page_says_not_connected_once_in_the_instagram_section_only():
    channels = make_channels(instagram_connected=False)

    html = render_settings(Overview(token=None, posts=[]), channels=channels)

    assert "Instagram ist noch nicht verbunden." in html
    # The switch form carries no hint of its own: the Instagram section right
    # above already says why publishing there is off.
    assert "Instagram ist nicht verbunden." not in html


def test_settings_page_offers_to_connect_when_instagram_is_not_connected():
    html = render_settings(Overview(token=None, posts=[]))

    assert "Instagram verbinden" in html
    assert 'href="/oauth/login"' in html
    assert "Instagram ist noch nicht verbunden." in html


def test_settings_page_shows_connected_without_a_sync_status_line():
    html = render_settings(connected())

    assert "Verbunden." in html
    assert "Läuft. Letzter Abgleich" not in html  # that line moved into the job block


def test_settings_page_offers_to_reconnect_when_the_token_is_expiring():
    html = render_settings(Overview(token=make_token(days_left=3), posts=[]))

    assert "in 3 Tagen" in html
    assert "Neu verbinden" in html


def test_settings_page_shows_the_public_base_url_readiness_hint():
    ready = render_settings(Overview(token=make_token(), posts=[]), channels=make_channels())
    not_ready = render_settings(
        Overview(token=make_token(), posts=[]),
        channels=make_channels(instagram_public_https=False),
    )

    assert "Instagram kann die Bilder dieser App laden." in ready
    assert "PUBLIC_BASE_URL ist keine öffentliche https-Adresse" not in ready
    assert "PUBLIC_BASE_URL ist keine öffentliche https-Adresse" in not_ready


# -- settings page: the Automatik section (jobs, runs, next_run) ---------------


def test_settings_job_that_never_ran():
    html = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(),))

    assert "Instagram-Abgleich" in html
    assert "Noch nicht gelaufen (seit dem Start)." in html


def test_settings_job_ok_shows_zuletzt_and_the_summary():
    run = JobRun(at=NOW - timedelta(minutes=4), summary="2 neue Posts · 1 zugestellt")

    html = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(runs=(run,)),))

    assert "Läuft. Zuletzt vor 4 Minuten." in html
    assert "2 neue Posts · 1 zugestellt" in html


def test_settings_job_error_shows_the_error_not_the_summary():
    run = JobRun(at=NOW - timedelta(minutes=1), error="boom", summary="sollte nicht erscheinen")

    html = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(runs=(run,)),))

    assert "Hakt. Zuletzt vor 1 Minute fehlgeschlagen." in html
    assert "boom" in html
    assert "sollte nicht erscheinen" not in html


def test_settings_job_sync_form_carries_next_to_einstellungen():
    html = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(),))

    assert "Jetzt abgleichen" in html
    assert 'name="next" value="/einstellungen"' in html


def test_settings_runs_details_only_shows_with_more_than_one_run():
    one_run = (JobRun(at=NOW, summary="x"),)
    two_runs = (
        JobRun(at=NOW, summary="x"),
        JobRun(at=NOW - timedelta(hours=1), error="boom"),
    )

    single = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(runs=one_run),))
    multiple = render_settings(
        Overview(token=None, posts=[]), jobs=(make_job_status(runs=two_runs),)
    )

    assert "<details" not in single
    assert "<details" in multiple
    assert "Letzte Läufe" in multiple
    assert "✓ x" in multiple
    assert "✕ " in multiple


def test_settings_job_shows_the_streak_line():
    without_streak = render_settings(
        Overview(token=None, posts=[]), jobs=(make_job_status(runs=(JobRun(at=NOW),)),)
    )
    with_streak = render_settings(
        Overview(token=None, posts=[]),
        jobs=(
            make_job_status(runs=(JobRun(at=NOW),), streak=Streak(current=37, best=120)),
        ),
    )

    assert "Serie:" not in without_streak  # default JobStatus() carries an empty Streak
    assert "Serie: 37 Läufe ohne Fehler. Rekord: 120." in with_streak


def test_settings_next_run_shows_relative_time_only_when_known():
    with_next = render_settings(
        Overview(token=None, posts=[]), next_run=NOW + timedelta(minutes=4)
    )
    without_next = render_settings(Overview(token=None, posts=[]), next_run=None)

    assert "Nächster Lauf in 4 Minuten" in with_next
    assert "Nächster Lauf" not in without_next


def test_settings_interval_wording_is_singular_with_one_job_plural_with_two():
    one_job = render_settings(Overview(token=None, posts=[]), jobs=(make_job_status(),))
    two_jobs = render_settings(
        Overview(token=None, posts=[]),
        jobs=(
            make_job_status(),
            make_job_status(
                key="calendar", label="Kalender-Abgleich", sync_action="/calendar/sync"
            ),
        ),
    )

    assert "läuft der Abgleich von selbst" in one_job
    assert "laufen die Abgleiche von selbst" in two_jobs


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
    assert "Warteschlange" not in html  # the pills are gone (round 5)
    assert "Einrichtung" not in html


def test_review_page_empty_state_carries_an_empty_line_and_the_inbox_zero_line():
    berlin = ZoneInfo("Europe/Berlin")
    expected_line = EMPTY_LINES[NOW.astimezone(berlin).timetuple().tm_yday % len(EMPTY_LINES)]

    html = render_review(ReviewQueue(drafts=[], posts=[]), inbox_zero="Seit 5 Minuten leer.")

    assert expected_line in html
    assert "Seit 5 Minuten leer." in html


def test_review_page_milestone_line():
    html = render_review(ReviewQueue(drafts=[], posts=[]), milestone=7)
    without = render_review(ReviewQueue(drafts=[], posts=[]), milestone=None)

    assert "Das war Freigabe Nummer 7." in html
    assert "Das war Freigabe Nummer" not in without


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


def test_review_page_draft_freigeben_and_ablehnen_share_one_actions_block():
    draft = PostDraft.new(
        caption="Hallo Welt", images=[DraftImage("image/jpeg", 1, 1, b"x")], now=NOW
    )
    review = DraftReview(draft=draft, image_urls=(), hint=None)

    html = render_review(ReviewQueue(drafts=[review], posts=[]))

    start = html.index('<div class="actions">')
    actions = html[start : html.index("</div>", start)]
    assert f'form="draft-approve-{draft.id}"' in actions
    assert f'form="draft-reject-{draft.id}"' in actions
    assert "btn-solid" in actions
    assert html.count('<div class="actions">') == 1


def test_review_page_post_block_lists_proposed_destinations_and_shares_one_actions_block():
    view = PostView(post=make_post(), deliveries=[])
    review = PostReview(view=view, proposed=[C1])

    html = render_review(ReviewQueue(drafts=[], posts=[review]))

    assert f'action="/freigabe/posts/{view.post.id}/approve"' in html
    assert f'action="/freigabe/posts/{view.post.id}/reject"' in html
    assert 'name="telegram" value="c1" checked' in html
    assert f'form="post-approve-{view.post.id}"' in html
    assert f'form="post-reject-{view.post.id}"' in html


def test_review_page_post_block_labels_the_checkbox_from_channels_falling_back_to_sink_label():
    view = PostView(post=make_post(), deliveries=[])
    review = PostReview(view=view, proposed=[C1, Destination("signal", "s1")])
    channels = make_channels(
        telegram=(TelegramChannel(destination=C1, label="Werkstatt-Chat", auto_publish=False),)
    )

    html = render_review(ReviewQueue(drafts=[], posts=[review]), channels=channels)

    assert "Werkstatt-Chat" in html  # matched by destination
    assert "Signal s1" in html  # no matching channel: sink_label + address


def test_review_page_post_block_shows_the_instagram_origin_line_under_the_caption():
    view = PostView(post=make_post(), deliveries=[])
    review = PostReview(view=view, proposed=[C1])

    html = render_review(ReviewQueue(drafts=[], posts=[review]))

    assert (
        'href="https://instagram.com/p/p1/" target="_blank" rel="noopener">Instagram ✓</a>'
        in html
    )


# -- Freigabe page: Verlauf (history) --------------------------------------------


def test_review_page_history_empty_state():
    html = render_review(ReviewQueue(drafts=[], posts=[]), history=())

    assert '<p class="eyebrow">Verlauf</p>' in html
    assert "Noch nichts entschieden." in html


def test_review_page_shows_the_reaction_line_under_verlauf():
    without = render_review(ReviewQueue(drafts=[], posts=[]), reaction=None)
    html = render_review(ReviewQueue(drafts=[], posts=[]), reaction="Entschieden nach 5 Minuten.")

    assert "Entschieden nach 5 Minuten." not in without
    assert "Entschieden nach 5 Minuten." in html
    assert html.index('<p class="eyebrow">Verlauf</p>') < html.index("Entschieden nach 5 Minuten.")


def test_review_page_history_approved_entry_links_to_the_post():
    entry = ReviewLogEntry.new(
        "post", ReviewOutcome.APPROVED, "Siebdruck-Nachmittag", (C1,), NOW, post_id="p1"
    )

    html = render_review(ReviewQueue(drafts=[], posts=[]), history=(entry,))

    assert '<div class="log">' in html
    assert 'href="/posts/p1" data-modal>Siebdruck-Nachmittag</a>' in html
    assert "Freigegeben → Telegram" in html


def test_review_page_history_rejected_entry_has_no_post_link():
    entry = ReviewLogEntry.new("draft", ReviewOutcome.REJECTED, "Verworfen", (), NOW)

    html = render_review(ReviewQueue(drafts=[], posts=[]), history=(entry,))

    assert "Verworfen</p>" in html
    assert 'href="/posts/' not in html
    assert "Abgelehnt" in html


def test_review_page_history_auto_entry_says_automatisch_veroeffentlicht():
    entry = ReviewLogEntry.new(
        "post", ReviewOutcome.AUTO, "Auto-Post", (C1,), NOW, post_id="p2"
    )

    html = render_review(ReviewQueue(drafts=[], posts=[]), history=(entry,))

    assert "Automatisch veröffentlicht → Telegram" in html


def test_review_page_history_entry_with_no_caption_says_ohne_text():
    entry = ReviewLogEntry.new("draft", ReviewOutcome.REJECTED, None, (), NOW)

    html = render_review(ReviewQueue(drafts=[], posts=[]), history=(entry,))

    assert "Ohne Text" in html


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


def test_compose_offers_ohne_post_fertig_only_with_an_event():
    hint = ComposeHint(event_id="e1", title="Plenum", caption="x", detail_url="/calendar/events/e1")

    with_event = render_compose(hint=hint, event="e1", cancel_url=hint.detail_url)
    without_event = render_compose()

    assert 'href="/calendar/events/e1">Ohne Post fertig</a>' in with_event
    assert "Ohne Post fertig" not in without_event


# -- the wizard: step indicator and the Termin step (wizard_event.html) -----------


def test_step_indicator_marks_the_current_step_on_all_three_wizard_pages():
    step1 = render_wizard_event()
    step2 = render_compose(enabled=True)
    step3 = render_compose_preview(enabled=True)

    assert '<span class="current">1 Termin</span>' in step1
    assert "2 Post" in step1
    assert "3 Vorschau" in step1
    assert '<span class="current">2 Post</span>' in step2
    assert '<span class="current">3 Vorschau</span>' in step3


def test_step_indicator_omits_termin_and_renumbers_when_the_calendar_is_off():
    html = templates.env.get_template("compose.html").render(
        caption="",
        hint=None,
        event="",
        channels=make_channels(),
        error=None,
        now=NOW,
        cancel_url="/",
    )

    assert "Termin" not in html
    assert '<span class="current">1 Post</span>' in html
    assert "2 Vorschau" in html


def test_wizard_event_shows_the_prefilled_fields_and_sub_calendar_checkboxes():
    html = render_wizard_event(make_prefill())

    assert 'value="Fest"' in html
    assert 'value="2026-09-12"' in html
    assert 'value="18:00"' in html
    assert 'value="22:00"' in html
    assert 'value="Ort"' in html
    assert 'value="Jona"' in html
    assert SUB_CALENDAR_OPTION.name in html
    assert "checked" in html


def test_wizard_event_offers_ohne_termin_weiter_only_without_a_post():
    without_post = render_wizard_event(post_id=None)
    with_post = render_wizard_event(post_id="p1")

    assert 'href="/posts/new">Ohne Termin weiter</a>' in without_post
    assert "Ohne Termin weiter" not in with_post


def test_wizard_event_shows_the_post_header_only_when_a_post_is_given():
    view = PostView(post=make_post(), deliveries=[])

    with_post = render_wizard_event(post_id="p1", view=view)
    without_post = render_wizard_event(post_id=None, view=None)

    assert "Siebdruck-Nachmittag, offen für alle" in with_post
    assert 'href="/posts/p1"' in with_post
    assert "Siebdruck-Nachmittag" not in without_post


def test_wizard_event_kicker_goes_back_to_the_post_when_one_is_given():
    with_post = render_wizard_event(post_id="p1")
    without_post = render_wizard_event(post_id=None)

    assert '<a class="plain back" href="/posts/p1">« Abbrechen</a>' in with_post
    assert '<a class="plain back" href="/">« Abbrechen</a>' in without_post


def test_wizard_event_shows_an_error_notice():
    html = render_wizard_event(error="Das Ende muss nach dem Beginn liegen.")

    assert '<div class="notice">' in html
    assert "Das Ende muss nach dem Beginn liegen." in html


# -- base.html: nav badge + Termin link ------------------------------------------


def test_base_layout_has_the_freigabe_badge_htmx_attributes():
    html = render_index(Overview(token=None, posts=[]))

    assert 'hx-get="/freigabe/count"' in html
    assert 'hx-trigger="load"' in html
    assert "Social Posts" in html


def test_nav_shows_einstellungen_and_never_a_neu_nav_link():
    ov = Overview(token=None, posts=[])
    enabled = build_templates(ZoneInfo("Europe/Berlin"), calendar_enabled=True)

    with_calendar = enabled.env.get_template("index.html").render(
        ov=ov,
        now=NOW,
        last_run=None,
        multi_target=False,
        events="all",
        event_options=display.EVENT_OPTIONS,
        source="all",
        source_options=display.SOURCE_OPTIONS,
        channels=make_channels(),
        review_count=0,
        activity=EMPTY_ACTIVITY,
        milestone=None,
    )
    without_calendar = render_index(ov)

    assert 'href="/einstellungen">Einstellungen</a>' in with_calendar
    assert 'href="/einstellungen">Einstellungen</a>' in without_calendar
    assert "+ Neu" not in with_calendar
    assert "+ Neu" not in without_calendar
