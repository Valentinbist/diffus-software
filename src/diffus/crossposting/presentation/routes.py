"""HTTP routes. Every route requires HTTP Basic auth."""

from __future__ import annotations

import contextlib
import html
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from diffus.crossposting.application.channels import all_auto
from diffus.crossposting.domain.entities import (
    Destination,
    DraftStatus,
    EventPrefill,
    NewEventRequest,
    PostDraft,
    PublishTargets,
    SubCalendarOption,
)
from diffus.crossposting.domain.errors import (
    ConnectorError,
    DraftError,
    EventCreationError,
    NotConnectedError,
)
from diffus.crossposting.presentation import display
from diffus.crossposting.presentation.services import Services, get_services
from diffus.shared.presentation.auth import require_auth
from diffus.shared.presentation.display import count_since, day_start, milestone
from diffus.shared.presentation.templates import build_templates as _build_shared_templates

router = APIRouter(dependencies=[Depends(require_auth)])

ServicesDep = Annotated[Services, Depends(get_services)]

# The compose wizard's upload limits — moved here from the calendar's own
# compose routes (round 3): the wizard now lives in crossposting regardless
# of whether it was reached with or without an event. See PostDraft.MAX_IMAGES
# for the per-draft image cap CreateDraft itself enforces; these two are the
# route-level limits on the raw multipart upload, checked before CreateDraft
# ever sees the bytes.
MAX_COMPOSE_IMAGES = 10
MAX_COMPOSE_BYTES = 20 * 1024 * 1024
COMPOSE_LIMIT_ERROR = "Höchstens 10 Bilder und 20 MB pro Post."


def _linked_event_id(draft: PostDraft | None) -> str | None:
    """The calendar event id a draft was started from, or None (no event, or draft missing)."""
    if draft is None or draft.event_ref is None or not draft.event_ref.startswith("calendar:"):
        return None
    return draft.event_ref.removeprefix("calendar:")


def build_templates(tz: ZoneInfo, calendar_enabled: bool = False) -> Jinja2Templates:
    """A Jinja2Templates instance with the display filters installed for `tz`."""
    shared_dir = Path(__file__).parent.parent.parent / "shared" / "presentation" / "templates"
    templates = _build_shared_templates(
        tz,
        [Path(__file__).parent / "templates", shared_dir],
        {"calendar_enabled": calendar_enabled},
    )
    templates.env.filters["delivery_label"] = display.delivery_label
    templates.env.filters["target_label"] = display.target_label
    templates.env.filters["sink_label"] = display.sink_label
    templates.env.filters["stored_cover"] = display.stored_cover
    templates.env.filters["source_label"] = display.source_label
    templates.env.filters["instagram_hint"] = display.instagram_hint
    templates.env.filters["channel_lines"] = display.channel_lines
    templates.env.filters["outcome_line"] = display.outcome_line
    return templates


@router.get("/")
async def index(request: Request, services: ServicesDep, events: str = "all", source: str = "all"):
    overview = await services.overview.run()
    if events not in {"with", "without"}:
        events = "all"
    if source not in {"instagram", "diffus"}:
        source = "all"
    overview.posts = display.filter_by_events(overview.posts, events)
    overview.posts = display.filter_by_source(overview.posts, source)
    review_count = await services.review_count.run()
    now = datetime.now(UTC)
    start = day_start(now, services.tz)
    # 17 weeks of slack for the heatmap's own 16-week window (build_templates'
    # `heatmap` filter re-derives the exact local Mon-Sun boundaries; a wider
    # cutoff here just avoids ever clipping it at a timezone edge).
    activity = await services.activity.run(start - timedelta(weeks=17))
    milestone_number = milestone(activity.total, count_since(activity.posted_at, start))
    return services.templates.TemplateResponse(
        request,
        "index.html",
        {
            "ov": overview,
            "now": now,
            "last_run": services.sync_job.last_run,
            "multi_target": len(services.destinations) > 1,
            "events": events,
            "event_options": display.EVENT_OPTIONS,
            "source": source,
            "source_options": display.SOURCE_OPTIONS,
            "review_count": review_count,
            "activity": activity,
            "milestone": milestone_number,
        },
    )


@router.post("/channels")
async def set_channels(
    services: ServicesDep,
    auto: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves this per request
):
    try:
        parsed = {Destination.parse(text) for text in auto}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad destination") from exc
    await services.set_auto_publish.run(parsed)
    # The switches live on /einstellungen (round 5: setup.html -> settings.html).
    return RedirectResponse("/einstellungen", status_code=303)


# -- Freigabe: the review queue -------------------------------------------------


async def _render_review(
    request: Request, services: Services, error: str | None = None, status_code: int = 200
):
    queue = await services.review_queue.run()
    channels = await services.channels.run()
    history = await services.review_history.run()
    now = datetime.now(UTC)
    stats = await services.review_stats.run(day_start(now, services.tz))
    queue_empty = not queue.drafts and not queue.posts
    return services.templates.TemplateResponse(
        request,
        "review.html",
        {
            "queue": queue,
            "channels": channels,
            "history": history,
            "now": now,
            "multi_target": len(services.destinations) > 1,
            "error": error,
            "stats": stats,
            "milestone": milestone(stats.decisions, stats.decided_today),
            # Only shown while the queue is actually empty right now: the log
            # can't yet know whether today's still-open stretch is a record
            # (see domain/stats.py).
            "inbox_zero": display.inbox_zero_line(stats, now) if queue_empty else None,
            "reaction": display.reaction_line(stats),
        },
        status_code=status_code,
    )


@router.get("/freigabe")
async def review_page(request: Request, services: ServicesDep):
    return await _render_review(request, services)


@router.get("/freigabe/setup")
async def setup_page_redirect() -> RedirectResponse:
    """Old bookmarks/links: the setup page moved to /einstellungen (round 5)."""
    return RedirectResponse("/einstellungen", status_code=303)


@router.get("/einstellungen")
async def settings_page(request: Request, services: ServicesDep):
    """Instagram connection, the channel switches, and the automation overview.

    Replaces /freigabe/setup (round 5, owner: "the setup thing needs to be
    moved to a settings thingy, where I would also like to have some view
    into the automation"). `services.overview` still carries the token (the
    one place that reads it), and `limit=0` skips fetching any posts for a
    page that never lists them.
    """
    overview = await services.overview.run(limit=0)
    channels = await services.channels.run()
    return services.templates.TemplateResponse(
        request,
        "settings.html",
        {
            "ov": overview,
            "now": datetime.now(UTC),
            "last_run": services.sync_job.last_run,
            "channels": channels,
            "automation": services.automation,
            "jobs": services.automation.jobs(),
            "next_run": services.automation.next_run(),
        },
    )


@router.get("/freigabe/count")
async def review_count_badge(services: ServicesDep):
    count = await services.review_count.run()
    if count <= 0:
        return HTMLResponse("")
    return HTMLResponse(f'<span class="badge">{count}</span>')


@router.get("/backdrop")
async def backdrop(services: ServicesDep):
    """The newest post's blurred cover, behind every page of every context.

    base.html fetches this with htmx after load, the same way it fetches the
    Freigabe badge — so the calendar's pages get the newest post's backdrop
    too, without the calendar context ever knowing posts exist.
    """
    overview = await services.overview.run(limit=5)
    url = display.backdrop_url(overview.posts)
    if url is None:
        return HTMLResponse("")
    return HTMLResponse(
        f'<div class="backdrop" style="background-image:url({html.escape(url)})"></div>',
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/freigabe/drafts/{draft_id}/approve")
async def approve_draft(
    request: Request,
    services: ServicesDep,
    draft_id: str,
    instagram: bool = Form(False),
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    targets = PublishTargets(
        instagram=instagram, destinations=tuple(Destination("telegram", a) for a in telegram)
    )
    try:
        post = await services.approve_draft.run(draft_id, targets)
    except (DraftError, NotConnectedError) as exc:
        return await _render_review(request, services, error=str(exc), status_code=400)
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    event_id = _linked_event_id(await services.get_draft.run(draft_id))
    if event_id is not None:
        return RedirectResponse(f"/calendar/events/{event_id}?published={post.id}", status_code=303)
    return RedirectResponse(f"/posts/{post.id}", status_code=303)


@router.post("/freigabe/drafts/{draft_id}/reject")
async def reject_draft(services: ServicesDep, draft_id: str):
    await services.reject_draft.run(draft_id)
    return RedirectResponse("/freigabe", status_code=303)


@router.post("/freigabe/posts/{post_id}/approve")
async def approve_post_deliveries(
    services: ServicesDep,
    post_id: str,
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    chosen = [Destination("telegram", a) for a in telegram]
    try:
        await services.approve_post.run(post_id, chosen)
    except ConnectorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@router.post("/freigabe/posts/{post_id}/reject")
async def reject_post_deliveries(services: ServicesDep, post_id: str):
    await services.reject_post.run(post_id)
    return RedirectResponse("/freigabe", status_code=303)


# -- The wizard, step 1: Termin -------------------------------------------------
#
# One flow, three steps — Termin (/neu) -> Post (/posts/new) -> Vorschau
# (/posts/new/{draft}) — each of the first two skippable. Registered before
# GET /posts/{post_id} for the same reason as the compose routes below:
# FastAPI matches routes in registration order.


def _event_prefill_from_options(prefill: EventPrefill) -> NewEventRequest:
    """The GET form's starting values: options.prefill has no location/who (see EventPrefill)."""
    return NewEventRequest(
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


async def _render_wizard_event(
    request: Request,
    services: Services,
    post_id: str | None,
    prefill: NewEventRequest,
    sub_calendars: tuple[SubCalendarOption, ...],
    error: str | None = None,
    status_code: int = 200,
):
    view = await services.detail.run(post_id) if post_id else None
    return services.templates.TemplateResponse(
        request,
        "wizard_event.html",
        {
            "post_id": post_id,
            "prefill": prefill,
            "sub_calendars": sub_calendars,
            "view": view,
            "error": error,
            "now": datetime.now(UTC),
        },
        status_code=status_code,
    )


@router.get("/neu")
async def wizard_event_get(request: Request, services: ServicesDep, post: str | None = None):
    options = await services.events.event_form(post)
    if options is None:
        # None means either "the calendar is off" (post is None: NoEvents
        # always answers None) or "post names an unknown post" — the two
        # never happen for the same request, so `post` alone disambiguates.
        if post is None:
            return RedirectResponse("/posts/new", status_code=303)
        raise HTTPException(status_code=404, detail="unknown post")
    prefill = _event_prefill_from_options(options.prefill)
    return await _render_wizard_event(
        request, services, options.post_id, prefill, options.sub_calendars
    )


@router.post("/neu")
async def wizard_event_post(
    request: Request,
    services: ServicesDep,
    post_id: str = Form(""),
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
    prefill = NewEventRequest(
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
        event = await services.events.create_event(prefill, post_id or None)
    except EventCreationError as exc:
        options = await services.events.event_form(post_id or None)
        sub_calendars = options.sub_calendars if options is not None else ()
        return await _render_wizard_event(
            request, services, post_id or None, prefill, sub_calendars, str(exc), 400
        )
    if post_id:
        # The calendar already linked the post itself (EventDirectory.create_event's
        # contract) — the wizard is done, step 2 never happens for this path.
        return RedirectResponse(f"/calendar/events/{event.id}", status_code=303)
    return RedirectResponse(f"/posts/new?event={event.id}", status_code=303)


# -- Compose wizard, steps 2 and 3: Post, then Vorschau --------------------------
#
# Registered between index() and GET /posts/{post_id} on purpose: FastAPI
# matches routes in registration order, and "/posts/new" would otherwise be
# swallowed by "/posts/{post_id}" (post_id="new").


async def _render_compose(
    request: Request,
    services: Services,
    caption: str,
    event: str,
    error: str | None = None,
    status_code: int = 200,
):
    hint = await services.events.compose_hint(event) if event else None
    channels = await services.channels.run()
    return services.templates.TemplateResponse(
        request,
        "compose.html",
        {
            "caption": caption,
            "hint": hint,
            "event": event,
            "channels": channels,
            "error": error,
            "now": datetime.now(UTC),
            "cancel_url": hint.detail_url if hint is not None else "/",
        },
        status_code=status_code,
    )


@router.get("/posts/new")
async def compose_get(request: Request, services: ServicesDep, event: str = ""):
    hint = None
    if event:
        hint = await services.events.compose_hint(event)
        if hint is None:
            raise HTTPException(status_code=404, detail="unknown event")
    channels = await services.channels.run()
    return services.templates.TemplateResponse(
        request,
        "compose.html",
        {
            "caption": hint.caption if hint is not None else "",
            "hint": hint,
            "event": event,
            "channels": channels,
            "error": None,
            "now": datetime.now(UTC),
            "cancel_url": hint.detail_url if hint is not None else "/",
        },
    )


@router.post("/posts/new")
async def compose_post(
    request: Request,
    services: ServicesDep,
    caption: str = Form(...),
    images: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI re-resolves per request
    instagram: bool = Form(False),
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
    event: str = Form(""),
):
    parts = [image for image in images if image.filename]
    if len(parts) > MAX_COMPOSE_IMAGES:
        return await _render_compose(request, services, caption, event, COMPOSE_LIMIT_ERROR, 413)

    uploads: list[tuple[str, bytes]] = []
    total = 0
    for image in parts:
        data = await image.read()
        total += len(data)
        if total > MAX_COMPOSE_BYTES:
            return await _render_compose(
                request, services, caption, event, COMPOSE_LIMIT_ERROR, 413
            )
        uploads.append((image.filename or "", data))

    try:
        draft = await services.create_draft.run(
            caption, uploads, event_ref=f"calendar:{event}" if event else None
        )
    except DraftError as exc:
        return await _render_compose(request, services, caption, event, str(exc), 400)

    pairs = [("instagram", "1")] if instagram else []
    pairs += [("telegram", address) for address in telegram]
    query = f"?{urlencode(pairs)}" if pairs else ""
    return RedirectResponse(f"/posts/new/{draft.id}{query}", status_code=303)


async def _render_compose_preview(
    request: Request,
    services: Services,
    draft_id: str,
    instagram: bool,
    telegram: list[str],
    error: str | None = None,
    status_code: int = 200,
):
    draft = await services.get_draft.run(draft_id)
    if draft is None or draft.status != DraftStatus.DRAFT:
        raise HTTPException(status_code=404, detail="unknown draft")
    hint = None
    if draft.event_ref is not None and draft.event_ref.startswith("calendar:"):
        hint = await services.events.compose_hint(draft.event_ref.removeprefix("calendar:"))
    channels = await services.channels.run()
    image_urls = tuple(f"/drafts/{draft.id}/media/{i}" for i in range(len(draft.images)))
    targets = PublishTargets(
        instagram=instagram, destinations=tuple(Destination("telegram", a) for a in telegram)
    )
    return services.templates.TemplateResponse(
        request,
        "compose_preview.html",
        {
            "draft": draft,
            "image_urls": image_urls,
            "hint": hint,
            "channels": channels,
            "instagram": instagram,
            "telegram": telegram,
            "all_auto": all_auto(channels.auto_map(), targets),
            "error": error,
            "now": datetime.now(UTC),
        },
        status_code=status_code,
    )


@router.get("/posts/new/{draft_id}")
async def compose_preview(
    request: Request,
    services: ServicesDep,
    draft_id: str,
    instagram: bool = False,
    telegram: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    return await _render_compose_preview(request, services, draft_id, instagram, telegram)


@router.post("/posts/new/{draft_id}/submit")
async def compose_submit(
    request: Request,
    services: ServicesDep,
    draft_id: str,
    instagram: bool = Form(False),
    telegram: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI re-resolves per request
):
    targets = PublishTargets(
        instagram=instagram, destinations=tuple(Destination("telegram", a) for a in telegram)
    )
    try:
        result = await services.submit_draft.run(draft_id, targets)
    except (DraftError, NotConnectedError) as exc:
        return await _render_compose_preview(
            request, services, draft_id, instagram, telegram, str(exc), 400
        )
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.queued:
        return RedirectResponse("/freigabe", status_code=303)

    assert result.post is not None  # narrowed: not queued means it published
    event_id = _linked_event_id(await services.get_draft.run(draft_id))
    if event_id is not None:
        return RedirectResponse(
            f"/calendar/events/{event_id}?published={result.post.id}", status_code=303
        )
    return RedirectResponse(f"/posts/{result.post.id}", status_code=303)


@router.post("/posts/new/{draft_id}/discard")
async def compose_discard(services: ServicesDep, draft_id: str):
    event_id = _linked_event_id(await services.get_draft.run(draft_id))
    await services.discard_draft.run(draft_id)
    if event_id is not None:
        return RedirectResponse(f"/calendar/events/{event_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/posts/{post_id}")
async def post_detail(request: Request, post_id: str, services: ServicesDep):
    view = await services.detail.run(post_id)
    if view is None:
        raise HTTPException(status_code=404, detail="unknown post")
    return services.templates.TemplateResponse(
        request,
        "post.html",
        {
            "view": view,
            "now": datetime.now(UTC),
            "multi_target": len(services.destinations) > 1,
        },
    )


@router.get("/posts/{post_id}/media/{index}")
async def post_media(post_id: str, index: int, services: ServicesDep):
    """The stored still image of one media item; the templates fall back to the CDN without it."""
    preview = await services.preview.run(post_id, index)
    if preview is None:
        raise HTTPException(status_code=404, detail="no stored preview")
    return Response(
        content=preview.data,
        media_type=preview.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/drafts/{draft_id}/media/{index}")
async def draft_media(draft_id: str, index: int, services: ServicesDep):
    """A still-unpublished draft's image, for the compose wizard's own preview.

    Authenticated (this router requires Basic auth already), unlike the
    public `GET /media/drafts/...` route on public_router — that one exists
    only so Instagram itself can fetch the image at publish time.
    """
    image = await services.draft_image.run(draft_id, index)
    if image is None:
        raise HTTPException(status_code=404, detail="no such draft image")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/sync")
async def sync_now(services: ServicesDep, next: str = Form("/")):
    # Same job the scheduler runs, so a manual sync also heals a stale token.
    await services.sync_job.run()
    # Only ever bounce back to one of our own pages — same guard as /resend.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(target, status_code=303)


@router.post("/resend")
async def resend(
    services: ServicesDep,
    post_id: str = Form(...),
    destination: str = Form(...),
    next: str = Form("/"),
):
    try:
        parsed = Destination.parse(destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad destination") from exc
    with contextlib.suppress(ConnectorError):
        await services.resend.run(post_id, parsed)
    # Only ever bounce back to one of our own pages.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(target, status_code=303)


@router.get("/oauth/login")
async def oauth_login(services: ServicesDep):
    return RedirectResponse(services.connect.authorize_url())


@router.get("/oauth/callback")
async def oauth_callback(services: ServicesDep, code: str):
    await services.connect.complete(code)
    return RedirectResponse("/", status_code=303)
