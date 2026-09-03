"""The calendar templates, rendered straight from the Jinja env, in the states the routes build."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from diffus.calendar.application.calendar_events import CalendarPage, EventPostStatus, EventView
from diffus.calendar.application.event_detail import EventDetail, SuggestedPost
from diffus.calendar.application.suggest_posts import SuggestionReason
from diffus.calendar.application.sync_job import CalendarLastRun
from diffus.calendar.domain.entities import CalendarEvent, EventLink, LinkablePost, SubCalendar
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
    }

    html = render_calendar(context)

    assert '<table class="grid"' in html
    assert html.count("<td") == 35
    assert 'href="/calendar/events/e1"' in html
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
