"""Composition root: builds the object graph and wires the FastAPI app + scheduler."""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from connector.application.connect_instagram import ConnectInstagram
from connector.application.deliver import DeliverPost
from connector.application.overview import GetOverview
from connector.application.post_detail import GetPostDetail
from connector.application.preview import GetPreview
from connector.application.refresh_token import EnsureFreshToken
from connector.application.resend_delivery import ResendDelivery
from connector.application.sync_job import SyncJob
from connector.application.sync_posts import SyncPosts
from connector.config import get_settings
from connector.domain.entities import Destination
from connector.infrastructure.db.session import make_engine, make_session_factory
from connector.infrastructure.db.uow import SqlUnitOfWork
from connector.infrastructure.instagram.client import InstagramClient
from connector.infrastructure.media.downloader import HttpMediaGateway
from connector.infrastructure.telegram.sink import TelegramSink
from connector.presentation.routes import build_templates, health_router, router
from connector.presentation.services import Services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Composition root: get_settings() is only ever called here (or in request-scoped
    # dependencies), never at import time, so `import connector.presentation.app`
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

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(job.run, "interval", minutes=settings.poll_interval_minutes)
    scheduler.start()

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
    else:
        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
