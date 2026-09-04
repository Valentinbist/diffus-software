"""Composition root: builds the object graph and wires the FastAPI app + scheduler."""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from diffus.calendar.application.calendar_events import GetCalendarEvents
from diffus.calendar.application.compose_post import GetComposeHint
from diffus.calendar.application.create_event import CreateEventForPost
from diffus.calendar.application.event_detail import GetEventDetail
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.link_picker import GetLinkPicker
from diffus.calendar.application.linked_events import GetLinkedEvents
from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.application.sync_job import CalendarSyncJob
from diffus.calendar.infrastructure.crossposting import CrosspostingPostCatalog
from diffus.calendar.infrastructure.db.uow import SqlCalendarUnitOfWork
from diffus.calendar.infrastructure.kalender_digital import KalenderDigitalClient
from diffus.calendar.presentation.routes import build_templates as build_calendar_templates
from diffus.calendar.presentation.routes import router as calendar_router
from diffus.calendar.presentation.services import CalendarServices
from diffus.crossposting.application.channels import GetChannels, SetAutoPublish
from diffus.crossposting.application.connect_instagram import ConnectInstagram
from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.drafts import (
    ApproveDraft,
    CreateDraft,
    DiscardDraft,
    GetDraft,
    GetDraftImage,
    SubmitDraft,
)
from diffus.crossposting.application.overview import GetOverview, NoEvents
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.preview import GetPreview
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.application.refresh_token import EnsureFreshToken
from diffus.crossposting.application.resend_delivery import ResendDelivery
from diffus.crossposting.application.review import (
    ApprovePostDeliveries,
    CountReview,
    GetReviewQueue,
    RejectPostDeliveries,
)
from diffus.crossposting.application.sync_job import SyncJob
from diffus.crossposting.application.sync_posts import SyncPosts
from diffus.crossposting.domain.entities import INSTAGRAM_CHANNEL, Destination
from diffus.crossposting.domain.ports import EventDirectory
from diffus.crossposting.infrastructure.calendar import CalendarEventDirectory
from diffus.crossposting.infrastructure.db.uow import SqlUnitOfWork
from diffus.crossposting.infrastructure.instagram.client import InstagramClient
from diffus.crossposting.infrastructure.media.downloader import HttpMediaGateway
from diffus.crossposting.infrastructure.media.fallback import FallbackMediaGateway
from diffus.crossposting.infrastructure.media.images import PillowImageProcessor
from diffus.crossposting.infrastructure.telegram.sink import TelegramSink
from diffus.crossposting.presentation.routes import ServicesDep, build_templates, router
from diffus.crossposting.presentation.services import Services
from diffus.shared.config import get_settings
from diffus.shared.db.session import make_engine, make_session_factory
from diffus.shared.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Built by `web/` (npm run build) into shared/presentation/static/dist; see
# shared/presentation/assets.py for how base.html resolves the hashed files.
STATIC_DIR = Path(__file__).parent / "shared" / "presentation" / "static"

# Unauthenticated on purpose: container and uptime probes can't carry Basic auth
# credentials, and neither can Instagram fetching a draft's images at publish
# time — see draft_public_media below.
public_router = APIRouter()


@public_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@public_router.get("/media/drafts/{draft_id}/{index}")
async def draft_public_media(draft_id: str, index: int, services: ServicesDep, key: str = ""):
    """What Instagram's `/media` endpoint fetches `image_url` from — see PostDraft.public_media_url.

    `key` must match the draft's own public_key (constant-time compare, done
    by GetDraftImage) or this 404s exactly like a missing draft/index would.
    """
    image = await services.draft_image.run(draft_id, index, key=key)
    if image is None:
        raise HTTPException(status_code=404, detail="no such draft image")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
    # FallbackMediaGateway is THE MediaGateway everywhere a post's media might
    # need to be re-fetched days after the CDN link went stale — a REVIEW
    # delivery approved late is the case that motivates it (see
    # infrastructure/media/fallback.py).
    media = FallbackMediaGateway(cdn=HttpMediaGateway(http), uow=uow)
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

    tz = ZoneInfo(settings.display_timezone)

    # The calendar is an optional second context: an empty token means no
    # calendar graph is built at all, not a graph that quietly does nothing.
    # Its unit of work is built here, before the crossposting read side, so
    # GetOverview/GetPostDetail can be given a real EventDirectory instead of
    # wiring it in after the fact.
    calendar_uow = None
    events: EventDirectory = NoEvents()
    if settings.calendar_enabled:
        calendar_uow = functools.partial(SqlCalendarUnitOfWork, session_factory)
        # The one exception to "contexts never import each other's
        # application layer": a context's adapter may call another context's
        # application read use cases (see docs/architecture.md, Bounded contexts).
        #
        # Composition-root cycle: CalendarEventDirectory.link() needs a
        # LinkEventPost, which needs a PostCatalog built from crossposting's
        # own overview/detail — but the *real* overview/detail (below) are
        # built with `events`, i.e. this very directory. Break the cycle with
        # a second, event-less catalog used only to validate a post id when
        # linking (LinkEventPost.add never reads an event's own linked
        # events, so NoEvents costs nothing here); the real catalog built
        # further down, from the real overview/detail, is what every page
        # actually uses.
        link_catalog = CrosspostingPostCatalog(
            overview=GetOverview(uow=uow, source=instagram.source, events=NoEvents()),
            detail=GetPostDetail(uow=uow, events=NoEvents()),
        )
        events = CalendarEventDirectory(
            linked=GetLinkedEvents(uow=calendar_uow),
            hint=GetComposeHint(uow=calendar_uow, tz=tz),
            link_post=LinkEventPost(uow=calendar_uow, posts=link_catalog),
        )

    overview = GetOverview(uow=uow, source=instagram.source, events=events)
    detail = GetPostDetail(uow=uow, events=events)

    publish_draft = PublishDraft(
        uow=uow,
        publisher=instagram,
        sinks=sinks,
        destinations=destinations,
        public_base_url=settings.public_base_url,
        # Shares SyncJob's own lock: publishing and the poller must never run
        # at the same time (see PublishDraft's module docstring).
        lock=job.lock,
        events=events,
    )

    create_draft = CreateDraft(uow=uow, images=PillowImageProcessor())
    discard_draft = DiscardDraft(uow=uow)
    get_draft = GetDraft(uow=uow)
    channels = GetChannels(
        uow=uow,
        source=instagram.source,
        destinations=destinations,
        public_base_url=settings.public_base_url,
    )
    # Every channel the app knows about, so a submitted form with some boxes
    # left unchecked can write "off" for them too (SetAutoPublish's full-set
    # semantics — see channels.py).
    known_channels = [INSTAGRAM_CHANNEL, *destinations]
    set_auto_publish = SetAutoPublish(uow=uow, channels=known_channels)
    submit_draft = SubmitDraft(uow=uow, publish=publish_draft, destinations=destinations)
    approve_draft = ApproveDraft(publish=publish_draft)
    review_queue = GetReviewQueue(uow=uow, detail=detail, events=events, destinations=destinations)
    review_count = CountReview(uow=uow)
    # Shares SyncJob's own lock too: a double-click-safe approve must not run
    # while the poller is mid-tick either (see review.py's docstring).
    approve_post = ApprovePostDeliveries(
        uow=uow, deliver=deliver, destinations=destinations, lock=job.lock
    )
    reject_post = RejectPostDeliveries(uow=uow)

    app.state.services = Services(
        sync_job=job,
        connect=ConnectInstagram(auth=instagram, uow=uow),
        resend=ResendDelivery(uow=uow, deliver=deliver),
        overview=overview,
        detail=detail,
        preview=GetPreview(uow=uow),
        destinations=destinations,
        templates=build_templates(tz, calendar_enabled=settings.calendar_enabled),
        create_draft=create_draft,
        publish_draft=publish_draft,
        discard_draft=discard_draft,
        get_draft=get_draft,
        draft_image=GetDraftImage(uow=uow),
        channels=channels,
        set_auto_publish=set_auto_publish,
        submit_draft=submit_draft,
        approve_draft=approve_draft,
        review_queue=review_queue,
        review_count=review_count,
        approve_post=approve_post,
        reject_post=reject_post,
        events=events,
    )

    calendar_services: CalendarServices | None = None
    if settings.calendar_enabled:
        assert calendar_uow is not None
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
        # Same exception, the other way round: the calendar's own adapter
        # over crossposting's read use cases (see docs/architecture.md,
        # Bounded contexts). This is the *real* catalog (built from the real
        # overview/detail, with `events` wired in) — not the event-less
        # `link_catalog` above, which only ever backs
        # CalendarEventDirectory.link()'s own LinkEventPost.
        catalog = CrosspostingPostCatalog(overview=overview, detail=detail)
        calendar_services = CalendarServices(
            sync_job=CalendarSyncJob(sync_calendar),
            calendar=GetCalendarEvents(uow=calendar_uow, posts=catalog, tz=tz),
            event_detail=GetEventDetail(uow=calendar_uow, posts=catalog, tz=tz),
            link_post=LinkEventPost(uow=calendar_uow, posts=catalog),
            link_picker=GetLinkPicker(uow=calendar_uow, posts=catalog, tz=tz),
            create_event=CreateEventForPost(
                uow=calendar_uow, posts=catalog, calendar=calendar_gateway, tz=tz
            ),
            tz=tz,
            templates=build_calendar_templates(tz, calendar_enabled=True),
        )
    app.state.calendar = calendar_services

    async def tick() -> None:
        # One interval job on purpose, running both contexts' syncs in
        # sequence, so "an interval trigger first fires one interval after
        # start" (docs/architecture.md, Sharp edges) only has to be true once.
        await job.run()
        if calendar_services is not None:
            await calendar_services.sync_job.run()

    scheduler = start_scheduler(tick, settings.poll_interval_minutes)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await http.aclose()
        await engine.dispose()


def create_app(
    services: Services | None = None, calendar: CalendarServices | None = None
) -> FastAPI:
    if services is not None:
        # Pre-built services (tests): skip the lifespan, so no real DB engine
        # or scheduler is started, and install the given object graph directly.
        app = FastAPI(docs_url=None, redoc_url=None)
        app.state.services = services
        app.state.calendar = calendar
    else:
        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(public_router)
    app.include_router(router)
    # Always mounted: get_calendar_services (its Depends) 404s when the
    # context is off, so the route table doesn't change with the feature flag.
    app.include_router(calendar_router)
    # Public, no auth: the built CSS/JS is not sensitive, and gating it behind
    # Basic auth would break the login-less error pages that link to it.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")
    return app


app = create_app()
