"""Composition root: builds the object graph and wires the FastAPI app + scheduler."""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, FastAPI

from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.application.sync_job import CalendarSyncJob
from diffus.calendar.infrastructure.db.uow import SqlCalendarUnitOfWork
from diffus.calendar.infrastructure.kalender_digital import KalenderDigitalClient
from diffus.crossposting.application.connect_instagram import ConnectInstagram
from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.overview import GetOverview
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.preview import GetPreview
from diffus.crossposting.application.refresh_token import EnsureFreshToken
from diffus.crossposting.application.resend_delivery import ResendDelivery
from diffus.crossposting.application.sync_job import SyncJob
from diffus.crossposting.application.sync_posts import SyncPosts
from diffus.crossposting.domain.entities import Destination
from diffus.crossposting.infrastructure.db.uow import SqlUnitOfWork
from diffus.crossposting.infrastructure.instagram.client import InstagramClient
from diffus.crossposting.infrastructure.media.downloader import HttpMediaGateway
from diffus.crossposting.infrastructure.telegram.sink import TelegramSink
from diffus.crossposting.presentation.routes import build_templates, router
from diffus.crossposting.presentation.services import Services
from diffus.shared.config import get_settings
from diffus.shared.db.session import make_engine, make_session_factory
from diffus.shared.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Unauthenticated on purpose: container and uptime probes can't carry Basic auth
# credentials. It reports liveness only — never connection or delivery state.
health_router = APIRouter()


@health_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Composition root: get_settings() is only ever called here (or in request-scoped
    # dependencies), never at import time, so `import diffus.app`
    # works without a .env file present.
    settings = get_settings()

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    uow = functools.partial(SqlUnitOfWork, session_factory)
    http = httpx.AsyncClient(timeout=30)

    instagram = InstagramClient(
        http,
        app_id=settings.ig_app_id,
        app_secret=settings.ig_app_secret,
        redirect_uri=settings.ig_redirect_uri,
    )
    telegram = TelegramSink(http, settings.telegram_bot_token)
    media = HttpMediaGateway(http)
    sinks = {"telegram": telegram}

    destinations = [Destination("telegram", c) for c in settings.chat_ids]

    deliver = DeliverPost(media=media, sinks=sinks, uow=uow)
    sync = SyncPosts(
        source=instagram,
        media=media,
        deliver=deliver,
        destinations=destinations,
        uow=uow,
    )
    job = SyncJob(sync=sync, refresh=EnsureFreshToken(auth=instagram, uow=uow))

    app.state.services = Services(
        sync_job=job,
        connect=ConnectInstagram(auth=instagram, uow=uow),
        resend=ResendDelivery(uow=uow, deliver=deliver),
        overview=GetOverview(uow=uow, source=instagram.source),
        detail=GetPostDetail(uow=uow),
        preview=GetPreview(uow=uow),
        destinations=destinations,
        templates=build_templates(ZoneInfo(settings.display_timezone)),
    )

    # The calendar is an optional second context: an empty token means no
    # calendar graph is built at all, not a graph that quietly does nothing.
    calendar_job: CalendarSyncJob | None = None
    if settings.calendar_enabled:
        calendar_uow = functools.partial(SqlCalendarUnitOfWork, session_factory)
        calendar_gateway = KalenderDigitalClient(
            http,
            token=settings.kalender_digital_token,
            api_base=settings.kalender_digital_api_base,
        )
        sync_calendar = SyncCalendar(
            calendar=calendar_gateway,
            uow=calendar_uow,
            past_months=settings.calendar_past_months,
            future_months=settings.calendar_future_months,
        )
        calendar_job = CalendarSyncJob(sync_calendar)
    app.state.calendar_sync_job = calendar_job

    async def tick() -> None:
        # One interval job on purpose, running both contexts' syncs in
        # sequence, so "an interval trigger first fires one interval after
        # start" (docs/architecture.md, Sharp edges) only has to be true once.
        await job.run()
        if calendar_job is not None:
            await calendar_job.run()

    scheduler = start_scheduler(tick, settings.poll_interval_minutes)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await http.aclose()
        await engine.dispose()


def create_app(services: Services | None = None) -> FastAPI:
    if services is not None:
        # Pre-built services (tests): skip the lifespan, so no real DB engine
        # or scheduler is started, and install the given object graph directly.
        app = FastAPI(docs_url=None, redoc_url=None)
        app.state.services = services
        app.state.calendar_sync_job = None
    else:
        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
