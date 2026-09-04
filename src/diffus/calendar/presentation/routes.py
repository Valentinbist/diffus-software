"""HTTP routes for the calendar context. Every route requires HTTP Basic auth."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from diffus.calendar.application.compose_post import ComposePrefill
from diffus.calendar.application.create_event import EventForm
from diffus.calendar.domain.errors import (
    CalendarError,
    PublishError,
    UnknownEventError,
    UnknownPostError,
)
from diffus.calendar.presentation import display
from diffus.calendar.presentation.services import CalendarServices, get_calendar_services
from diffus.shared.presentation.auth import require_auth
from diffus.shared.presentation.templates import build_templates as _build_shared_templates

MAX_COMPOSE_IMAGES = 10
MAX_COMPOSE_BYTES = 20 * 1024 * 1024
COMPOSE_LIMIT_ERROR = "Höchstens 10 Bilder und 20 MB pro Post."

router = APIRouter(prefix="/calendar", dependencies=[Depends(require_auth)])

ServicesDep = Annotated[CalendarServices, Depends(get_calendar_services)]


def today(tz: ZoneInfo) -> date:
    return datetime.now(UTC).astimezone(tz).date()


def _month_label_filter(text: str) -> str:
    """`grid.prev`/`grid.next` are always well-formed "YYYY-MM" strings we generated ourselves."""
    parsed = display.parse_month(text)
    assert parsed is not None
    return display.month_label(*parsed)


def build_templates(tz: ZoneInfo, calendar_enabled: bool = True) -> Jinja2Templates:
    """A Jinja2Templates instance with the calendar + shared display filters installed for `tz`."""
    shared_dir = Path(__file__).parent.parent.parent / "shared" / "presentation" / "templates"
    templates = _build_shared_templates(
        tz,
        [Path(__file__).parent / "templates", shared_dir],
        {"calendar_enabled": calendar_enabled},
    )
    templates.env.filters["agenda_day"] = lambda day, now: display.format_agenda_day(day, now, tz)
    templates.env.filters["event_time"] = lambda event: display.format_event_time(event, tz)
    templates.env.filters["by_day"] = lambda views, floor: display.by_day(views, floor, tz)
    templates.env.filters["month_grid"] = lambda views, year, month, now: display.month_grid(
        views, year, month, now, tz
    )
    templates.env.filters["month_label"] = _month_label_filter
    templates.env.filters["post_status_label"] = display.post_status_label
    templates.env.filters["reason_label"] = display.reason_label
    templates.env.filters["instagram_hint"] = display.instagram_hint
    return templates


@router.get("")
async def calendar_page(
    request: Request,
    services: ServicesDep,
    view: str = "agenda",
    from_: Annotated[str | None, Query(alias="from")] = None,
    month: str | None = None,
    cal: Annotated[list[int], Query()] = [],  # noqa: B006 - FastAPI re-resolves this per request
    status: str = "all",
):
    now = datetime.now(UTC)
    selected = set(cal)
    cal_qs = "".join(f"&cal={c}" for c in cal)
    if status not in {"linked", "unlinked"}:
        status = "all"
    status_qs = "" if status == "all" else f"&status={status}"
    context: dict[str, object] = {
        "selected": selected,
        "cal_qs": cal_qs,
        "now": now,
        "last_run": services.sync_job.last_run,
        "status": status,
        "status_qs": status_qs,
        "status_pills": display.STATUS_PILLS,
    }

    if view == "month":
        current = (today(services.tz).year, today(services.tz).month)
        year, month_num = display.parse_month(month) or current
        start_day, end_day = display.month_range(year, month_num)
        page = await services.calendar.run(start_day, end_day, sub_calendar_ids=cal)
        page.events = display.filter_by_status(page.events, status)
        context |= {
            "page": page,
            "view": "month",
            "grid": display.month_grid(page.events, year, month_num, now, services.tz),
            "month_value": f"{year:04d}-{month_num:02d}",
        }
    else:
        from_day = display.parse_day(from_) or today(services.tz)
        end_day = from_day + timedelta(days=27)
        page = await services.calendar.run(from_day, end_day, sub_calendar_ids=cal)
        page.events = display.filter_by_status(page.events, status)
        context |= {
            "page": page,
            "view": "agenda",
            "from_day": from_day,
            "prev_from": from_day - timedelta(days=28),
            "next_from": from_day + timedelta(days=28),
        }
    return services.templates.TemplateResponse(request, "calendar.html", context)


@router.post("/sync")
async def sync_now(services: ServicesDep):
    # Same job the scheduler runs, so a manual sync also surfaces a stale run.
    await services.sync_job.run()
    return RedirectResponse("/calendar", status_code=303)


# Registered before /events/{event_id} so "link" is never swallowed as an event id.
@router.get("/link")
async def link_picker(request: Request, services: ServicesDep, post: str = Query(...)):
    picker = await services.link_picker.run(post, datetime.now(UTC))
    if picker is None:
        raise HTTPException(status_code=404, detail="unknown post")
    return services.templates.TemplateResponse(
        request, "link.html", {"picker": picker, "now": datetime.now(UTC)}
    )


@router.post("/link")
async def link_from_post(
    services: ServicesDep,
    post_id: str = Form(...),
    event_id: str = Form(...),
    next: str = Form(""),
):
    try:
        await services.link_post.add(event_id, post_id)
    except (UnknownEventError, UnknownPostError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Only ever bounce back to one of our own pages.
    target = next if next.startswith("/") and not next.startswith("//") else f"/posts/{post_id}"
    return RedirectResponse(target, status_code=303)


async def _rerender_new_event(
    request: Request,
    services: CalendarServices,
    post_id: str,
    form: EventForm,
    error: str,
    status_code: int,
):
    result = await services.create_event.prefill(post_id)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown post")
    post, _prefill, sub_calendars = result
    return services.templates.TemplateResponse(
        request,
        "new_event.html",
        {
            "post": post,
            "form": form,
            "sub_calendars": sub_calendars,
            "error": error,
            "now": datetime.now(UTC),
        },
        status_code=status_code,
    )


# Registered before /events/{event_id} so "new" is never swallowed as an event id.
@router.get("/events/new")
async def new_event_get(request: Request, services: ServicesDep, post: str = Query(...)):
    result = await services.create_event.prefill(post)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown post")
    linkable_post, prefill, sub_calendars = result
    form = EventForm(
        title=prefill.title,
        day=prefill.day,
        start=prefill.start,
        end=prefill.end,
        whole_day=prefill.whole_day,
        description=prefill.description,
        location="",
        who="",
        sub_calendar_ids=prefill.sub_calendar_ids,
    )
    return services.templates.TemplateResponse(
        request,
        "new_event.html",
        {
            "post": linkable_post,
            "form": form,
            "sub_calendars": sub_calendars,
            "error": None,
            "now": datetime.now(UTC),
        },
    )


@router.post("/events/new")
async def new_event_post(
    request: Request,
    services: ServicesDep,
    post_id: str = Form(...),
    title: str = Form(...),
    day: date = Form(...),  # noqa: B008 - fastapi.Form, not a mutable default
    start: time = Form(...),  # noqa: B008 - fastapi.Form, not a mutable default
    end: time = Form(...),  # noqa: B008 - fastapi.Form, not a mutable default
    whole_day: bool = Form(False),
    description: str = Form(""),
    location: str = Form(""),
    who: str = Form(""),
    cal: Annotated[list[int], Form()] = [],  # noqa: B006 - FastAPI re-resolves this per request
):
    form = EventForm(
        title=title,
        day=day,
        start=start,
        end=end,
        whole_day=whole_day,
        description=description,
        location=location,
        who=who,
        sub_calendar_ids=frozenset(cal),
    )
    try:
        event = await services.create_event.create(post_id, form)
    except UnknownPostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        return await _rerender_new_event(request, services, post_id, form, str(exc), 400)
    except CalendarError as exc:
        return await _rerender_new_event(request, services, post_id, form, str(exc), 502)
    return RedirectResponse(f"/calendar/events/{event.id}", status_code=303)


@router.get("/events/{event_id}")
async def event_detail(
    request: Request, services: ServicesDep, event_id: str, published: str | None = None
):
    detail = await services.event_detail.run(event_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown event")
    back_from = detail.view.event.starts_at.astimezone(services.tz).date().isoformat()
    return services.templates.TemplateResponse(
        request,
        "event.html",
        {
            "detail": detail,
            "now": datetime.now(UTC),
            "back_from": back_from,
            "published": published,
        },
    )


@router.post("/events/{event_id}/link")
async def link_event(services: ServicesDep, event_id: str, post_id: str = Form(...)):
    try:
        await services.link_post.add(event_id, post_id)
    except (UnknownEventError, UnknownPostError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(f"/calendar/events/{event_id}", status_code=303)


@router.post("/events/{event_id}/unlink")
async def unlink_event(
    services: ServicesDep,
    event_id: str,
    post_id: str = Form(...),
    next: str = Form("/calendar"),
):
    await services.link_post.remove(event_id, post_id)
    # Only ever bounce back to one of our own pages.
    target = next if next.startswith("/") and not next.startswith("//") else "/calendar"
    return RedirectResponse(target, status_code=303)


async def _rerender_compose(
    request: Request,
    services: CalendarServices,
    event_id: str,
    caption: str,
    error: str,
    status_code: int,
):
    form = await services.compose.prefill(event_id)
    if form is None:
        raise HTTPException(status_code=404, detail="unknown event")
    form = dataclasses.replace(form, prefill=ComposePrefill(caption=caption))
    return services.templates.TemplateResponse(
        request,
        "compose.html",
        {"form": form, "error": error, "now": datetime.now(UTC)},
        status_code=status_code,
    )


@router.get("/events/{event_id}/compose")
async def compose_get(request: Request, services: ServicesDep, event_id: str):
    form = await services.compose.prefill(event_id)
    if form is None:
        raise HTTPException(status_code=404, detail="unknown event")
    return services.templates.TemplateResponse(
        request, "compose.html", {"form": form, "error": None, "now": datetime.now(UTC)}
    )


@router.post("/events/{event_id}/compose")
async def compose_post(
    request: Request,
    services: ServicesDep,
    event_id: str,
    caption: str = Form(...),
    images: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI re-resolves per request
    instagram: bool = Form(False),
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    parts = [image for image in images if image.filename]
    if len(parts) > MAX_COMPOSE_IMAGES:
        return await _rerender_compose(
            request, services, event_id, caption, COMPOSE_LIMIT_ERROR, 413
        )

    uploads: list[tuple[str, bytes]] = []
    total = 0
    for image in parts:
        data = await image.read()
        total += len(data)
        if total > MAX_COMPOSE_BYTES:
            return await _rerender_compose(
                request, services, event_id, caption, COMPOSE_LIMIT_ERROR, 413
            )
        uploads.append((image.filename or "", data))

    try:
        draft_id = await services.compose.start(event_id, caption, uploads)
    except UnknownEventError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PublishError as exc:
        return await _rerender_compose(request, services, event_id, caption, str(exc), 400)

    pairs = [("instagram", "1")] if instagram else []
    pairs += [("telegram", address) for address in telegram]
    query = f"?{urlencode(pairs)}" if pairs else ""
    return RedirectResponse(
        f"/calendar/events/{event_id}/compose/{draft_id}{query}", status_code=303
    )


@router.get("/events/{event_id}/compose/{draft_id}")
async def compose_preview(
    request: Request,
    services: ServicesDep,
    event_id: str,
    draft_id: str,
    instagram: bool = False,
    telegram: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    preview = await services.compose.preview(event_id, draft_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="unknown event or draft")
    return services.templates.TemplateResponse(
        request,
        "compose_preview.html",
        {
            "preview": preview,
            "instagram": instagram,
            "telegram": telegram,
            "error": None,
            "now": datetime.now(UTC),
        },
    )


@router.post("/events/{event_id}/compose/{draft_id}/publish")
async def compose_publish(
    request: Request,
    services: ServicesDep,
    event_id: str,
    draft_id: str,
    instagram: bool = Form(False),
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    try:
        published = await services.compose.publish(event_id, draft_id, instagram, telegram)
    except PublishError as exc:
        preview = await services.compose.preview(event_id, draft_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="unknown event or draft") from exc
        return services.templates.TemplateResponse(
            request,
            "compose_preview.html",
            {
                "preview": preview,
                "instagram": instagram,
                "telegram": telegram,
                "error": str(exc),
                "now": datetime.now(UTC),
            },
            status_code=502,
        )
    return RedirectResponse(
        f"/calendar/events/{event_id}?published={published.id}", status_code=303
    )


@router.post("/events/{event_id}/compose/{draft_id}/discard")
async def compose_discard(services: ServicesDep, event_id: str, draft_id: str):
    await services.compose.discard(draft_id)
    return RedirectResponse(f"/calendar/events/{event_id}", status_code=303)
