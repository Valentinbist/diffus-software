"""HTTP routes. Every route requires HTTP Basic auth except /healthz."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from connector.domain.errors import ConnectorError
from connector.presentation import display
from connector.presentation.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

# Unauthenticated on purpose: container and uptime probes can't carry Basic auth
# credentials. It reports liveness only — never connection or delivery state.
health_router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def configure_templates(tz: ZoneInfo) -> None:
    """Install the display filters. Called by the composition root once settings are known."""
    templates.env.filters["when"] = lambda dt, now: display.format_when(dt, now, tz)
    templates.env.filters["day"] = lambda dt, now: display.format_day(dt, now, tz)
    templates.env.filters["ago"] = display.format_ago
    templates.env.filters["summary"] = display.summary
    templates.env.filters["error_text"] = display.error_text
    templates.env.filters["delivery_label"] = display.delivery_label
    templates.env.filters["stored_cover"] = display.stored_cover


@health_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/")
async def index(request: Request):
    state = request.app.state
    overview = await state.overview.run()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "ov": overview,
            "now": datetime.now(UTC),
            "last_run": state.sync_job.last_run,
            "multi_chat": len(state.chat_ids) > 1,
        },
    )


@router.get("/posts/{post_id}")
async def post_detail(request: Request, post_id: str):
    state = request.app.state
    view = await state.detail.run(post_id)
    if view is None:
        raise HTTPException(status_code=404, detail="unknown post")
    return templates.TemplateResponse(
        request,
        "post.html",
        {"view": view, "now": datetime.now(UTC), "multi_chat": len(state.chat_ids) > 1},
    )


@router.get("/posts/{post_id}/media/{index}")
async def post_media(request: Request, post_id: str, index: int):
    """The stored still image of one media item; the templates fall back to the CDN without it."""
    preview = await request.app.state.previews.get(post_id, index)
    if preview is None:
        raise HTTPException(status_code=404, detail="no stored preview")
    return Response(
        content=preview.data,
        media_type=preview.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/sync")
async def sync_now(request: Request):
    # Same job the scheduler runs, so a manual sync also heals a stale token.
    await request.app.state.sync_job.run()
    return RedirectResponse("/", status_code=303)


@router.post("/resend")
async def resend(
    request: Request,
    post_id: str = Form(...),
    chat_id: str = Form(...),
    next: str = Form("/"),
):
    with contextlib.suppress(ConnectorError):
        await request.app.state.resend.run(post_id, chat_id)
    # Only ever bounce back to one of our own pages.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(target, status_code=303)


@router.get("/oauth/login")
async def oauth_login(request: Request):
    return RedirectResponse(request.app.state.connect.authorize_url())


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str):
    await request.app.state.connect.complete(code)
    return RedirectResponse("/", status_code=303)
