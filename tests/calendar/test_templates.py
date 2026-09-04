"""The calendar templates, rendered straight from the Jinja env, in the states the routes build."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import CalendarPage, EventPostStatus, EventView
from diffus.calendar.application.compose_post import ComposeForm, ComposePrefill, ComposePreview
from diffus.calendar.application.create_event import EventForm
from diffus.calendar.application.event_detail import EventDetail, SuggestedPost
from diffus.calendar.application.link_picker import LinkPicker, LinkPickerEvent
from diffus.calendar.application.suggest_posts import SuggestionReason
from diffus.calendar.application.sync_job import CalendarLastRun
from diffus.calendar.domain.entities import (
    CalendarEvent,
    DraftPreview,
    EventLink,
    InstagramState,
    LinkablePost,
    PublishOptions,
    SubCalendar,
    TelegramTarget,
)
from diffus.calendar.presentation import display
from diffus.calendar.presentation.routes import build_templates

TZ = ZoneInfo("Europe/Berlin")
templates = build_templates(TZ)

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # Donnerstag, 3. September in Berlin
TOKEN = "03e3bc8e2be173ff9c8b"

SUB_CALENDAR = SubCalendar(
    id=5298948, name="Öffentliche Veranstaltung", color="#9BBB59", position=0
)


def make_event(
    event_id: str = "e1",
    title: str = "Widersetzen Plenum",
    starts_at: datetime = datetime(2026, 9, 3, 16, 0, tzinfo=UTC),  # 18:00 CEST
    ends_at: datetime | None = None,
    removed_at: datetime | None = None,
    who: str | None = None,
    description: str | None = None,
    location: str | None = None,
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        description=description,
        who=who,
        location=location,
        starts_at=starts_at,
        ends_at=ends_at if ends_at is not None else starts_at + timedelta(hours=2),
        whole_day=False,
        sub_calendar_ids=frozenset({SUB_CALENDAR.id}),
        series_id=None,
        removed_at=removed_at,
    )


def make_post(
    post_id: str = "p1", delivered: bool = True, caption: str | None = "Text"
) -> LinkablePost:
    return LinkablePost(
        id=post_id,
        caption=caption,
        permalink=f"https://instagram.com/p/{post_id}/",
        posted_at=NOW - timedelta(hours=1),
        thumbnail_url=None,
        detail_url=f"/posts/{post_id}",
        delivered=delivered,
    )


def make_view(
    event: CalendarEvent, status: EventPostStatus = EventPostStatus.DELIVERED, links=None
) -> EventView:
    return EventView(
        event=event, sub_calendars=[SUB_CALENDAR], links=links or [], post_status=status
    )


def render_calendar(context: dict) -> str:
    return templates.env.get_template("calendar.html").render(**context)


def render_event(context: dict) -> str:
    return templates.env.get_template("event.html").render(**context)


def agenda_context(**overrides) -> dict:
    event = make_event()
    view = make_view(event)
    page = CalendarPage(sub_calendars=[SUB_CALENDAR], events=[view])
    from_day = NOW.astimezone(TZ).date()
    context = {
        "page": page,
        "view": "agenda",
        "from_day": from_day,
        "prev_from": from_day - timedelta(days=28),
        "next_from": from_day + timedelta(days=28),
        "selected": {SUB_CALENDAR.id},
        "cal_qs": f"&cal={SUB_CALENDAR.id}",
        "now": NOW,
        "last_run": CalendarLastRun(at=NOW - timedelta(minutes=5)),
        "status": "all",
        "status_qs": "",
        "status_pills": display.STATUS_PILLS,
    }
    context.update(overrides)
    return context


# -- agenda view ----------------------------------------------------------------


def test_agenda_view_shows_the_day_heading_time_sub_calendar_dot_and_post_status():
    html = render_calendar(agenda_context())

    assert "Heute · Donnerstag, 3. September" in html
    assert "18:00–20:00" in html
    assert SUB_CALENDAR.name in html
    assert 'style="background:#9BBB59"' in html
    assert "Post verknüpft · zugestellt ✓" in html
    assert 'class="meta attention"' in html
    assert "checked" in html
    # Jinja autoescapes "&" to "&amp;" in attribute values, as valid HTML requires.
    assert 'href="/calendar?view=month&amp;cal=5298948">Monat' in html
    assert "Jetzt abgleichen" in html


def test_agenda_status_line_shows_a_redacted_sync_error():
    error = (
        f"Server error '500' for url "
        f"'https://api.kalender.digital/event?capabilityId={TOKEN}&startDate=2026-08-01'"
    )
    html = render_calendar(
        agenda_context(last_run=CalendarLastRun(at=NOW - timedelta(minutes=5), error=error))
    )

    assert "ist fehlgeschlagen" in html
    assert "capabilityId=…" in html
    assert TOKEN not in html


# -- month view -------------------------------------------------------------------


def test_month_view_renders_a_35_cell_grid_with_a_delivered_event_marked():
    event = make_event()
    view = make_view(event, status=EventPostStatus.DELIVERED)
    grid = display.month_grid([view], 2026, 9, NOW, TZ)
    page = CalendarPage(sub_calendars=[SUB_CALENDAR], events=[view])
    context = {
        "page": page,
        "view": "month",
        "grid": grid,
        "selected": set(),
        "cal_qs": "",
        "now": NOW,
        "last_run": None,
        "month_value": "2026-09",
        "status": "all",
        "status_qs": "",
        "status_pills": display.STATUS_PILLS,
    }

    html = render_calendar(context)

    assert '<table class="grid"' in html
    assert html.count("<td") == 35
    assert 'href="/calendar/events/e1"' in html
    assert "data-modal" in html
    assert "✓ " in html


# -- event page -------------------------------------------------------------------


def event_context(**overrides) -> dict:
    event = make_event(
        who="Jona", description="Kommt vorbei!", title="<script>alert(1)</script>"
    )
    view = make_view(
        event,
        status=EventPostStatus.DELIVERED,
        links=[EventLink(event_id=event.id, post_id="p-linked", linked_at=NOW)],
    )
    detail = EventDetail(
        view=view,
        linked=[make_post("p-linked", delivered=True)],
        suggestions=[
            SuggestedPost(
                post=make_post("p-suggested", delivered=False), reasons=(SuggestionReason.DATE,)
            )
        ],
        recent=[make_post("p-recent", delivered=False)],
    )
    context = {"detail": detail, "now": NOW, "back_from": "2026-09-03"}
    context.update(overrides)
    return context


def test_event_page_shows_linked_and_suggested_posts_and_escapes_the_title():
    html = render_event(event_context())

    assert "Verknüpfung lösen" in html
    assert "Verknüpfen" in html
    assert 'name="next" value="/calendar/events/e1"' in html
    assert "Datum steht im Text" in html
    assert "Eingetragen von Jona" in html
    assert "Kommt vorbei!" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_event_page_shows_the_removed_notice_for_a_deleted_event():
    event = make_event(removed_at=NOW - timedelta(days=1))
    view = make_view(event)
    detail = EventDetail(view=view, linked=[], suggestions=[], recent=[])

    html = render_event({"detail": detail, "now": NOW, "back_from": "2026-09-03"})

    assert "Dieser Termin wurde im Kalender gelöscht" in html


# -- nav + secret hygiene -----------------------------------------------------------


def test_nav_shows_the_calendar_link_marked_current_on_a_calendar_page():
    html = render_event(event_context())

    assert 'class="plain current" href="/calendar"' in html


def test_the_capability_token_never_leaks_into_rendered_html():
    error = f"boom capabilityId={TOKEN}"
    agenda_html = render_calendar(
        agenda_context(last_run=CalendarLastRun(at=NOW, error=error))
    )
    event_html = render_event(event_context())

    assert TOKEN not in agenda_html
    assert TOKEN not in event_html


def test_base_layout_has_the_topbar_brand_and_modal_dialog():
    html = render_event(event_context())

    assert 'class="topbar"' in html
    assert ">diffus.space<" in html
    assert '<dialog id="modal"' in html
    assert '<div class="page">' in html
    assert 'href="/static/dist/' in html


# -- status filter pills -----------------------------------------------------------


def test_status_pills_mark_the_current_filter_and_link_to_the_others():
    html = render_calendar(agenda_context(status="linked"))

    assert '<span class="pill current">Mit Post</span>' in html
    assert (
        'href="/calendar?view=agenda&from=2026-09-03&amp;cal=5298948&status=unlinked"' in html
    )
    assert 'href="/calendar?view=agenda&from=2026-09-03&amp;cal=5298948">Alle</a>' in html


def test_agenda_and_pager_links_carry_the_status_filter():
    html = render_calendar(agenda_context(status="unlinked", status_qs="&status=unlinked"))

    assert "status=unlinked" in html
    assert html.count("status=unlinked") >= 3  # toggle + both pager directions + Heute


# -- link picker page ---------------------------------------------------------------


def make_link_picker() -> LinkPicker:
    post = make_post("p1", caption="Siebdruck-Nachmittag")
    suggested = make_event(event_id="e-sugg", starts_at=datetime(2026, 9, 5, 16, 0, tzinfo=UTC))
    upcoming = make_event(event_id="e-up", starts_at=datetime(2026, 9, 20, 16, 0, tzinfo=UTC))
    return LinkPicker(
        post=post,
        suggestions=[
            LinkPickerEvent(
                event=suggested,
                sub_calendars=[SUB_CALENDAR],
                reasons=(SuggestionReason.RECENT,),
                linked=False,
            )
        ],
        events=[
            LinkPickerEvent(
                event=upcoming, sub_calendars=[SUB_CALENDAR], reasons=(), linked=True
            )
        ],
    )


def test_link_picker_page_shows_suggestions_and_the_upcoming_list():
    html = templates.env.get_template("link.html").render(picker=make_link_picker(), now=NOW)

    assert "Mit Termin verknüpfen" in html
    assert "Siebdruck-Nachmittag" in html
    assert "Vorschläge" in html
    assert "Kurz vor dem Termin gepostet" in html
    assert "Termine der nächsten 60 Tage" in html
    assert "Verknüpft ✓" in html
    assert '<a class="plain back" href="/posts/p1">« Zum Post</a>' in html


# -- compose page -------------------------------------------------------------------


def make_compose_form(
    instagram_state: InstagramState = InstagramState.READY, caption: str = "Fest\n📅 Text"
) -> ComposeForm:
    event = make_event()
    view = make_view(event)
    options = PublishOptions(
        instagram=instagram_state, targets=(TelegramTarget(address="c1", label="Telegram"),)
    )
    return ComposeForm(view=view, prefill=ComposePrefill(caption=caption), options=options)


def test_compose_page_shows_the_prefilled_caption_and_the_checked_telegram_target():
    html = templates.env.get_template("compose.html").render(
        form=make_compose_form(), error=None, now=NOW
    )

    assert "Post erstellen" in html
    assert "Fest\n📅 Text" in html
    assert 'name="telegram" value="c1" checked' in html
    assert "disabled" not in html


def test_compose_page_disables_instagram_and_shows_the_hint_when_not_connected():
    html = templates.env.get_template("compose.html").render(
        form=make_compose_form(instagram_state=InstagramState.NOT_CONNECTED), error=None, now=NOW
    )

    assert "disabled" in html
    assert "Instagram ist nicht verbunden." in html


def test_compose_page_shows_an_error_notice():
    html = templates.env.get_template("compose.html").render(
        form=make_compose_form(), error="Höchstens 10 Bilder und 20 MB pro Post.", now=NOW
    )

    assert '<div class="notice">' in html
    assert "Höchstens 10 Bilder" in html


# -- compose preview page ------------------------------------------------------------


def make_compose_preview(image_urls=("/drafts/d1/media/0", "/drafts/d1/media/1")) -> ComposePreview:
    event = make_event()
    view = make_view(event)
    options = PublishOptions(
        instagram=InstagramState.READY, targets=(TelegramTarget(address="c1", label="Telegram"),)
    )
    draft = DraftPreview(id="d1", caption="Hallo Welt", image_urls=image_urls)
    return ComposePreview(view=view, draft=draft, options=options)


def test_compose_preview_page_shows_the_images_caption_and_hidden_chosen_targets():
    html = templates.env.get_template("compose_preview.html").render(
        preview=make_compose_preview(), instagram=False, telegram=["c1"], error=None, now=NOW
    )

    assert "Vorschau" in html
    assert 'src="/drafts/d1/media/0"' in html
    assert 'src="/drafts/d1/media/1"' in html
    assert "Hallo Welt" in html
    assert '<input type="hidden" name="telegram" value="c1">' in html
    assert "Telegram" in html


def test_compose_preview_page_shows_an_error_notice():
    html = templates.env.get_template("compose_preview.html").render(
        preview=make_compose_preview(), instagram=False, telegram=[], error="Instagram: boom",
        now=NOW,
    )

    assert '<div class="notice">' in html
    assert "Instagram: boom" in html


# -- new event page -------------------------------------------------------------------


def make_event_form() -> EventForm:
    return EventForm(
        title="Fest",
        day=date(2026, 9, 12),
        start=time(18, 0),
        end=time(22, 0),
        whole_day=False,
        description="Text",
        location="Ort",
        who="Jona",
        sub_calendar_ids=frozenset({SUB_CALENDAR.id}),
    )


def test_new_event_page_shows_the_post_header_and_the_prefilled_form():
    post = make_post("p1", caption="Sommerfest")
    html = templates.env.get_template("new_event.html").render(
        post=post, form=make_event_form(), sub_calendars=[SUB_CALENDAR], error=None, now=NOW
    )

    assert "Termin anlegen" in html
    assert "Sommerfest" in html
    assert 'value="Fest"' in html
    assert 'value="2026-09-12"' in html
    assert 'value="18:00"' in html
    assert 'value="22:00"' in html
    assert 'value="Ort"' in html
    assert 'value="Jona"' in html
    assert SUB_CALENDAR.name in html
    assert "checked" in html


def test_new_event_page_shows_an_error_notice():
    post = make_post("p1")
    html = templates.env.get_template("new_event.html").render(
        post=post,
        form=make_event_form(),
        sub_calendars=[SUB_CALENDAR],
        error="Das Ende muss nach dem Beginn liegen.",
        now=NOW,
    )

    assert '<div class="notice">' in html
    assert "Das Ende muss nach dem Beginn liegen." in html
