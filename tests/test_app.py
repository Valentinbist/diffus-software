"""End-to-end-ish tests against the ASGI app: real lifespan wiring, and pages on fakes.

Uses httpx.ASGITransport, not Starlette's deprecated TestClient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

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
from connector.domain.entities import Destination, MediaItem, MediaType, Post, Preview
from connector.presentation.app import create_app, lifespan
from connector.presentation.routes import build_templates
from connector.presentation.services import Services
from tests.fakes import FakeAuth, FakeMedia, FakeSink, FakeUnitOfWork, StaticSource


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

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/healthz")

        assert resp.status_code == 200


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


def make_services(uow: FakeUnitOfWork, sink: FakeSink, media: FakeMedia) -> Services:
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
        overview=GetOverview(uow=uow, source="instagram"),
        detail=GetPostDetail(uow=uow),
        preview=GetPreview(uow=uow),
        destinations=destinations,
        templates=build_templates(ZoneInfo("Europe/Berlin")),
    )


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
