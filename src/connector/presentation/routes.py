"""HTTP routes. Every route requires HTTP Basic auth except /healthz."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from connector.domain.errors import ConnectorError
from connector.presentation.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

# Unauthenticated on purpose: container and uptime probes can't carry Basic auth
# credentials. It reports liveness only — never connection or delivery state.
health_router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@health_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/")
async def index(request: Request):
    overview = await request.app.state.overview.run()
    return templates.TemplateResponse(
        request, "index.html", {"ov": overview, "now": datetime.now(UTC)}
    )


@router.post("/sync")
async def sync_now(request: Request):
    # Same job the scheduler runs, so a manual sync also heals a stale token.
    await request.app.state.sync_job.run()
    return RedirectResponse("/", status_code=303)


@router.post("/resend")
async def resend(request: Request, post_id: str = Form(...), chat_id: str = Form(...)):
    with contextlib.suppress(ConnectorError):
        await request.app.state.resend.run(post_id, chat_id)
    return RedirectResponse("/", status_code=303)


@router.get("/oauth/login")
async def oauth_login(request: Request):
    return RedirectResponse(request.app.state.connect.authorize_url())


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str):
    await request.app.state.connect.complete(code)
    return RedirectResponse("/", status_code=303)
