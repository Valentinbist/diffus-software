"""Composition root: builds the object graph and wires the FastAPI app + scheduler."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from connector.application.connect_instagram import ConnectInstagram
from connector.application.overview import GetOverview
from connector.application.post_detail import GetPostDetail
from connector.application.refresh_token import EnsureFreshToken
from connector.application.resend_delivery import ResendDelivery
from connector.application.sync_posts import SyncPosts
from connector.config import get_settings
from connector.infrastructure.db.repositories import (
    SqlDeliveryRepository,
    SqlPostRepository,
    SqlPreviewRepository,
    SqlTokenRepository,
)
from connector.infrastructure.db.session import make_engine, make_session_factory
from connector.infrastructure.instagram.client import InstagramClient
from connector.infrastructure.media.downloader import HttpMediaGateway
from connector.infrastructure.telegram.sink import TelegramSink
from connector.presentation.jobs import SyncJob
from connector.presentation.routes import configure_templates, health_router, router

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
    http = httpx.AsyncClient(timeout=30)

    posts = SqlPostRepository(session_factory)
    deliveries = SqlDeliveryRepository(session_factory)
    tokens = SqlTokenRepository(session_factory)
    previews = SqlPreviewRepository(session_factory)

    instagram = InstagramClient(http, settings, tokens)
    telegram = TelegramSink(http, settings.telegram_bot_token)
    media = HttpMediaGateway(http)

    sync = SyncPosts(
        source=instagram,
        posts=posts,
        deliveries=deliveries,
        media=media,
        previews=previews,
        sink=telegram,
        chat_ids=settings.chat_ids,
    )
    connect = ConnectInstagram(auth=instagram, tokens=tokens)
    refresh = EnsureFreshToken(auth=instagram, tokens=tokens)
    resend = ResendDelivery(posts=posts, deliveries=deliveries, media=media, sink=telegram)
    overview = GetOverview(tokens=tokens, posts=posts, deliveries=deliveries, previews=previews)
    detail = GetPostDetail(posts=posts, deliveries=deliveries, previews=previews)

    job = SyncJob(sync=sync, refresh=refresh)

    app.state.sync_job = job
    app.state.connect = connect
    app.state.resend = resend
    app.state.overview = overview
    app.state.detail = detail
    app.state.previews = previews
    app.state.chat_ids = settings.chat_ids
    configure_templates(ZoneInfo(settings.display_timezone))

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(job.run, "interval", minutes=settings.poll_interval_minutes)
    scheduler.start()

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await http.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
