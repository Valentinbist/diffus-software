"""HTTP routes. Every route requires HTTP Basic auth except /healthz."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from connector.domain.entities import Destination
from connector.domain.errors import ConnectorError
from connector.presentation import display
from connector.presentation.auth import require_auth
from connector.presentation.services import Services, get_services

router = APIRouter(dependencies=[Depends(require_auth)])

# Unauthenticated on purpose: container and uptime probes can't carry Basic auth
# credentials. It reports liveness only — never connection or delivery state.
health_router = APIRouter()

ServicesDep = Annotated[Services, Depends(get_services)]


def build_templates(tz: ZoneInfo) -> Jinja2Templates:
    """A Jinja2Templates instance with the display filters installed for `tz`."""
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.filters["when"] = lambda dt, now: display.format_when(dt, now, tz)
    templates.env.filters["day"] = lambda dt, now: display.format_day(dt, now, tz)
    templates.env.filters["ago"] = display.format_ago
    templates.env.filters["summary"] = display.summary
    templates.env.filters["error_text"] = display.error_text
    templates.env.filters["delivery_label"] = display.delivery_label
    templates.env.filters["target_label"] = display.target_label
    templates.env.filters["stored_cover"] = display.stored_cover
    return templates


@health_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/")
async def index(request: Request, services: ServicesDep):
    overview = await services.overview.run()
    return services.templates.TemplateResponse(
        request,
        "index.html",
        {
            "ov": overview,
            "now": datetime.now(UTC),
            "last_run": services.sync_job.last_run,
            "multi_target": len(services.destinations) > 1,
        },
    )


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


@router.post("/sync")
async def sync_now(services: ServicesDep):
    # Same job the scheduler runs, so a manual sync also heals a stale token.
    await services.sync_job.run()
    return RedirectResponse("/", status_code=303)


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
