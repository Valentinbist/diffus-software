"""End-to-end-ish tests against the ASGI app: real lifespan wiring, and pages on fakes.

Uses httpx.ASGITransport, not Starlette's deprecated TestClient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from diffus.app import create_app, lifespan
from diffus.calendar.application.calendar_events import GetCalendarEvents
from diffus.calendar.application.event_detail import GetEventDetail
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.link_picker import GetLinkPicker
from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.application.sync_job import CalendarSyncJob
from diffus.calendar.domain.entities import CalendarEvent, CalendarSnapshot, LinkablePost
from diffus.calendar.presentation.routes import build_templates as build_calendar_templates
from diffus.calendar.presentation.services import CalendarServices
from diffus.crossposting.application.connect_instagram import ConnectInstagram
from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.overview import GetOverview, NoEvents
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.preview import GetPreview
from diffus.crossposting.application.refresh_token import EnsureFreshToken
from diffus.crossposting.application.resend_delivery import ResendDelivery
from diffus.crossposting.application.sync_job import SyncJob
from diffus.crossposting.application.sync_posts import SyncPosts
from diffus.crossposting.domain.entities import (
    Destination,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
    Preview,
)
from diffus.crossposting.domain.ports import EventDirectory
from diffus.crossposting.presentation.routes import build_templates
from diffus.crossposting.presentation.services import Services
from diffus.shared.config import get_settings
from tests.calendar.fakes import FakeCalendar, FakeCalendarUnitOfWork, FakeEvents, FakePostCatalog
from tests.crossposting.fakes import (
    FakeAuth,
    FakeEventDirectory,
    FakeMedia,
    FakeSink,
    FakeUnitOfWork,
    StaticSource,
)


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1:1/x")
    monkeypatch.setenv("IG_APP_ID", "app-id")
    monkeypatch.setenv("IG_APP_SECRET", "app-secret")
    monkeypatch.setenv("IG_REDIRECT_URI", "https://example.com/oauth/callback")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "c1,c2")
    monkeypatch.setenv("BASIC_AUTH_USERNAME", "u")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "p")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "Europe/Berlin")
    # Explicitly off: a dev checkout's own .env (not read in CI, but pydantic-settings
    # falls back to it locally) may carry a real token, which would silently flip
    # calendar_enabled for every test that doesn't ask for it.
    monkeypatch.setenv("KALENDER_DIGITAL_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_lifespan_builds_the_whole_graph_without_a_database(settings_env):
    app = create_app()

    async with lifespan(app):
        assert isinstance(app.state.services, Services)
        assert list(app.state.services.destinations) == [
            Destination("telegram", "c1"),
            Destination("telegram", "c2"),
        ]
        # No KALENDER_DIGITAL_TOKEN in settings_env: the calendar graph is
        # not built at all, not built-but-idle.
        assert app.state.calendar is None

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/healthz")

        assert resp.status_code == 200


async def test_lifespan_builds_the_calendar_graph_when_a_token_is_set(settings_env, monkeypatch):
    monkeypatch.setenv("KALENDER_DIGITAL_TOKEN", "03e3bc8e2be173ff9c8b")
    get_settings.cache_clear()
    app = create_app()

    async with lifespan(app):
        assert isinstance(app.state.calendar, CalendarServices)


async def make_uow() -> FakeUnitOfWork:
    uow = FakeUnitOfWork()
    post = Post(
        id="p1",
        source="instagram",
        caption="Hello",
        permalink="https://instagram.com/p/p1/",
        media=(MediaItem(url="https://cdn.example.com/p1.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    await uow.posts.upsert(post)
    await uow.previews.save(
        Preview(post_id="p1", index=0, content_type="image/jpeg", data=b"stored-bytes")
    )
    await uow.commit()
    return uow


def make_services(
    uow: FakeUnitOfWork,
    sink: FakeSink,
    media: FakeMedia,
    events: EventDirectory | None = None,
) -> Services:
    events = events if events is not None else NoEvents()
    auth = FakeAuth()
    destinations = [Destination("telegram", "c1"), Destination("telegram", "c2")]
    deliver = DeliverPost(media=media, sinks={"telegram": sink}, uow=uow)
    sync = SyncPosts(
        source=StaticSource([]), media=media, deliver=deliver, destinations=destinations, uow=uow
    )
    job = SyncJob(sync=sync, refresh=EnsureFreshToken(auth=auth, uow=uow))
    return Services(
        sync_job=job,
        connect=ConnectInstagram(auth=auth, uow=uow),
        resend=ResendDelivery(uow=uow, deliver=deliver),
        overview=GetOverview(uow=uow, source="instagram", events=events),
        detail=GetPostDetail(uow=uow, events=events),
        preview=GetPreview(uow=uow),
        destinations=destinations,
        templates=build_templates(ZoneInfo("Europe/Berlin")),
    )


def make_calendar_uow() -> tuple[FakeCalendarUnitOfWork, FakePostCatalog]:
    event = CalendarEvent(
        id="e1",
        title="Widersetzen Plenum",
        description=None,
        who=None,
        location=None,
        starts_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
        whole_day=False,
        sub_calendar_ids=frozenset(),
        series_id=None,
    )
    uow = FakeCalendarUnitOfWork(events=FakeEvents([event]))
    post = LinkablePost(
        id="p1",
        caption="Text",
        permalink="https://instagram.com/p/p1/",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
        thumbnail_url=None,
        detail_url="/posts/p1",
        delivered=False,
    )
    return uow, FakePostCatalog([post])


def make_calendar_services(
    uow: FakeCalendarUnitOfWork, catalog: FakePostCatalog
) -> CalendarServices:
    tz = ZoneInfo("Europe/Berlin")
    snapshot = CalendarSnapshot(sub_calendars=(), events=())
    sync = SyncCalendar(calendar=FakeCalendar(snapshot), uow=uow)
    return CalendarServices(
        sync_job=CalendarSyncJob(sync),
        calendar=GetCalendarEvents(uow=uow, posts=catalog, tz=tz),
        event_detail=GetEventDetail(uow=uow, posts=catalog, tz=tz),
        link_post=LinkEventPost(uow=uow, posts=catalog),
        link_picker=GetLinkPicker(uow=uow, posts=catalog, tz=tz),
        tz=tz,
        templates=build_calendar_templates(tz, calendar_enabled=True),
    )


async def test_calendar_pages_and_linking_work_on_fakes(settings_env):
    uow, catalog = make_calendar_uow()
    calendar_services = make_calendar_services(uow, catalog)
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=calendar_services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/calendar")
        assert resp.status_code == 200
        assert "Widersetzen Plenum" in resp.text

        resp = await client.get("/calendar?view=month&month=2026-09")
        assert resp.status_code == 200

        resp = await client.get("/calendar/events/e1")
        assert resp.status_code == 200

        resp = await client.post("/calendar/events/e1/link", data={"post_id": "p1"})
        assert resp.status_code == 303

        resp = await client.get("/calendar/events/e1")
        assert "Verknüpfte Posts" in resp.text
        assert "/posts/p1" in resp.text

        resp = await client.post("/calendar/events/e1/unlink", data={"post_id": "p1"})
        assert resp.status_code == 303

        resp = await client.get("/calendar/events/nope")
        assert resp.status_code == 404

        resp = await client.post("/calendar/sync")
        assert resp.status_code == 303


async def test_calendar_status_filter_hides_a_linked_event_and_the_pager_carries_it(settings_env):
    uow, catalog = make_calendar_uow()
    calendar_services = make_calendar_services(uow, catalog)
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=calendar_services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        await client.post("/calendar/events/e1/link", data={"post_id": "p1"})

        resp = await client.get("/calendar?status=unlinked")
        assert "Widersetzen Plenum" not in resp.text
        assert "status=unlinked" in resp.text

        resp = await client.get("/calendar?status=linked")
        assert "Widersetzen Plenum" in resp.text


async def test_index_events_filter_shows_only_posts_with_a_linked_event(settings_env):
    event = LinkedEvent(
        id="e1",
        title="Widersetzen Plenum",
        starts_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
        detail_url="/calendar/events/e1",
    )
    events = FakeEventDirectory({"p1": [event]})
    services = make_services(await make_uow(), FakeSink(), FakeMedia(), events=events)
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/?events=with")
        assert "Hello" in resp.text
        assert "Widersetzen Plenum" in resp.text

        resp = await client.get("/?events=without")
        assert "Hello" not in resp.text


async def test_link_from_the_post_side_stores_the_link_and_bounces_back(settings_env):
    uow, catalog = make_calendar_uow()
    calendar_services = make_calendar_services(uow, catalog)
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=calendar_services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/calendar/link?post=p1")
        assert resp.status_code == 200
        assert "Widersetzen Plenum" in resp.text

        resp = await client.post(
            "/calendar/link", data={"post_id": "p1", "event_id": "e1", "next": "/posts/p1"}
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/posts/p1"

        resp = await client.get("/calendar/events/e1")
        assert "/posts/p1" in resp.text

        resp = await client.get("/calendar/link?post=nope")
        assert resp.status_code == 404


async def test_static_files_are_served_without_auth(settings_env):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/static/dist/nope.js")

    assert resp.status_code == 404


async def test_calendar_routes_404_and_the_nav_hides_the_link_when_the_calendar_is_disabled(
    settings_env,
):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/calendar")
        assert resp.status_code == 404

        resp = await client.get("/")
        assert 'href="/calendar"' not in resp.text

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200


async def test_pages_and_resend_work_on_fakes(settings_env):
    uow = await make_uow()
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Crossposting" in resp.text

        resp = await client.get("/posts/p1")
        assert resp.status_code == 200

        resp = await client.get("/posts/p1/media/0")
        assert resp.status_code == 200
        assert resp.content == b"stored-bytes"

        resp = await client.get("/posts/nope")
        assert resp.status_code == 404

        resp = await client.post("/resend", data={"post_id": "p1", "destination": "telegram:c1"})
        assert resp.status_code == 303
        assert sink.calls == [("p1", "c1")]

        resp = await client.post("/resend", data={"post_id": "p1", "destination": "nonsense"})
        assert resp.status_code == 400

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/")

    assert resp.status_code == 401
