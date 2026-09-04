"""End-to-end-ish tests against the ASGI app: real lifespan wiring, and pages on fakes.

Uses httpx.ASGITransport, not Starlette's deprecated TestClient.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from diffus.app import create_app, lifespan
from diffus.calendar.application.calendar_events import GetCalendarEvents
from diffus.calendar.application.create_event import CreateEventForPost
from diffus.calendar.application.event_detail import GetEventDetail
from diffus.calendar.application.link_event_post import LinkEventPost
from diffus.calendar.application.link_picker import GetLinkPicker
from diffus.calendar.application.sync_calendar import SyncCalendar
from diffus.calendar.application.sync_job import CalendarSyncJob
from diffus.calendar.domain.entities import CalendarEvent, CalendarSnapshot, LinkablePost
from diffus.calendar.presentation.routes import build_templates as build_calendar_templates
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
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    AccessToken,
    ComposeHint,
    Destination,
    DraftImage,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    Preview,
    Token,
)
from diffus.crossposting.domain.ports import EventDirectory
from diffus.crossposting.presentation.routes import build_templates
from diffus.crossposting.presentation.services import Services
from diffus.shared.config import get_settings
from tests.calendar.fakes import FakeCalendar, FakeCalendarUnitOfWork, FakeEvents, FakePostCatalog
from tests.crossposting.fakes import (
    FakeAuth,
    FakeEventDirectory,
    FakeImageProcessor,
    FakeMedia,
    FakePublisher,
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
    source: StaticSource | None = None,
) -> Services:
    events = events if events is not None else NoEvents()
    auth = FakeAuth()
    destinations = [Destination("telegram", "c1"), Destination("telegram", "c2")]
    deliver = DeliverPost(media=media, sinks={"telegram": sink}, uow=uow)
    sync = SyncPosts(
        source=source if source is not None else StaticSource([]),
        media=media,
        deliver=deliver,
        destinations=destinations,
        uow=uow,
    )
    job = SyncJob(sync=sync, refresh=EnsureFreshToken(auth=auth, uow=uow))
    publisher = FakePublisher()
    publish_draft = PublishDraft(
        uow=uow,
        publisher=publisher,
        sinks={"telegram": sink},
        destinations=destinations,
        public_base_url="https://example.com",
        lock=job.lock,
        events=events,
    )
    detail = GetPostDetail(uow=uow, events=events)
    return Services(
        sync_job=job,
        connect=ConnectInstagram(auth=auth, uow=uow),
        resend=ResendDelivery(uow=uow, deliver=deliver),
        overview=GetOverview(uow=uow, source="instagram", events=events),
        detail=detail,
        preview=GetPreview(uow=uow),
        destinations=destinations,
        templates=build_templates(ZoneInfo("Europe/Berlin")),
        create_draft=CreateDraft(uow=uow, images=FakeImageProcessor()),
        publish_draft=publish_draft,
        discard_draft=DiscardDraft(uow=uow),
        get_draft=GetDraft(uow=uow),
        draft_image=GetDraftImage(uow=uow),
        channels=GetChannels(
            uow=uow, source="instagram", destinations=destinations, public_base_url="https://example.com"
        ),
        set_auto_publish=SetAutoPublish(uow=uow, channels=[INSTAGRAM_CHANNEL, *destinations]),
        submit_draft=SubmitDraft(uow=uow, publish=publish_draft, destinations=destinations),
        approve_draft=ApproveDraft(publish=publish_draft),
        review_queue=GetReviewQueue(
            uow=uow, detail=detail, events=events, destinations=destinations
        ),
        review_count=CountReview(uow=uow),
        approve_post=ApprovePostDeliveries(
            uow=uow, deliver=deliver, destinations=destinations, lock=job.lock
        ),
        reject_post=RejectPostDeliveries(uow=uow),
        events=events,
    )


def make_calendar_uow() -> tuple[FakeCalendarUnitOfWork, FakePostCatalog]:
    # Anchored to the real "today" in Berlin, not a fixed date, so the event always
    # falls inside the calendar route's default (today-forward) agenda window.
    berlin = ZoneInfo("Europe/Berlin")
    today_local = datetime.now(berlin).date()
    starts_at = datetime(
        today_local.year, today_local.month, today_local.day, 18, 0, tzinfo=berlin
    ).astimezone(UTC)
    ends_at = datetime(
        today_local.year, today_local.month, today_local.day, 20, 0, tzinfo=berlin
    ).astimezone(UTC)
    event = CalendarEvent(
        id="e1",
        title="Widersetzen Plenum",
        description=None,
        who=None,
        location=None,
        starts_at=starts_at,
        ends_at=ends_at,
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
    uow: FakeCalendarUnitOfWork,
    catalog: FakePostCatalog,
) -> CalendarServices:
    tz = ZoneInfo("Europe/Berlin")
    snapshot = CalendarSnapshot(sub_calendars=(), events=())
    calendar_gateway = FakeCalendar(snapshot)
    sync = SyncCalendar(calendar=calendar_gateway, uow=uow)
    return CalendarServices(
        sync_job=CalendarSyncJob(sync),
        calendar=GetCalendarEvents(uow=uow, posts=catalog, tz=tz),
        event_detail=GetEventDetail(uow=uow, posts=catalog, tz=tz),
        link_post=LinkEventPost(uow=uow, posts=catalog),
        link_picker=GetLinkPicker(uow=uow, posts=catalog, tz=tz),
        create_event=CreateEventForPost(uow=uow, posts=catalog, calendar=calendar_gateway, tz=tz),
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


async def make_uow_with_draft() -> tuple[FakeUnitOfWork, PostDraft]:
    uow = await make_uow()
    draft = PostDraft.new(
        "caption",
        [DraftImage("image/jpeg", 1, 1, b"draft-bytes")],
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    await uow.drafts.add(draft)
    await uow.commit()
    return uow, draft


async def test_public_draft_media_route_serves_the_image_only_with_the_right_key(settings_env):
    uow, draft = await make_uow_with_draft()
    services = make_services(uow, FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/media/drafts/{draft.id}/0", params={"key": draft.public_key}
        )
        assert resp.status_code == 200
        assert resp.content == b"draft-bytes"
        assert resp.headers["cache-control"] == "public, max-age=86400"

        resp = await client.get(f"/media/drafts/{draft.id}/0", params={"key": "wrong-key"})
        assert resp.status_code == 404

        resp = await client.get(f"/media/drafts/{draft.id}/0")  # no key at all
        assert resp.status_code == 404


async def test_authenticated_draft_media_route_requires_auth_and_serves_the_image(settings_env):
    uow, draft = await make_uow_with_draft()
    services = make_services(uow, FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/drafts/{draft.id}/media/0")
        assert resp.status_code == 401

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get(f"/drafts/{draft.id}/media/0")
        assert resp.status_code == 200
        assert resp.content == b"draft-bytes"
        assert resp.headers["cache-control"] == "private, max-age=86400"


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
        assert "Social Posts" in resp.text

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


async def test_new_event_wizard_is_prefilled_and_posting_it_creates_and_links_the_event(
    settings_env,
):
    uow, catalog = make_calendar_uow()
    calendar_services = make_calendar_services(uow, catalog)
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=calendar_services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/calendar/events/new?post=p1")
        assert resp.status_code == 200
        assert "Termin anlegen" in resp.text

        resp = await client.post(
            "/calendar/events/new",
            data={
                "post_id": "p1",
                "title": "Neuer Termin",
                "day": "2026-09-10",
                "start": "18:00",
                "end": "20:00",
                "description": "",
                "location": "",
                "who": "",
            },
        )
        assert resp.status_code == 303

        resp = await client.get(resp.headers["location"])
        assert resp.status_code == 200
        assert "/posts/p1" in resp.text


async def test_standalone_new_event_wizard_works_without_a_post(settings_env):
    uow, catalog = make_calendar_uow()
    calendar_services = make_calendar_services(uow, catalog)
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services, calendar=calendar_services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/calendar/events/new")
        assert resp.status_code == 200
        assert "Termin anlegen" in resp.text

        resp = await client.post(
            "/calendar/events/new",
            data={
                "title": "Spontaner Termin",
                "day": "2026-09-10",
                "start": "18:00",
                "end": "20:00",
                "description": "",
                "location": "",
                "who": "",
            },
        )
        assert resp.status_code == 303

        resp = await client.get(resp.headers["location"])
        assert resp.status_code == 200
        assert "Noch kein Post verknüpft." in resp.text


# -- round 3: the crossposting compose wizard, Freigabe queue, and channel switches --

ONE_BY_ONE_PNG = b"fake-1x1-png-bytes"


async def test_compose_wizard_queues_for_freigabe_then_approval_delivers_via_telegram(
    settings_env,
):
    uow = await make_uow()
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post(
            "/posts/new",
            data={"caption": "Hallo", "telegram": "c1"},
            files=[("images", ("a.png", ONE_BY_ONE_PNG, "image/png"))],
        )
        assert resp.status_code == 303
        preview_url = resp.headers["location"]
        assert preview_url.startswith("/posts/new/")
        draft_id = preview_url.split("?")[0].rsplit("/", 1)[-1]

        resp = await client.get(preview_url)
        assert resp.status_code == 200
        assert "Zur Freigabe" in resp.text

        resp = await client.post(preview_url.split("?")[0] + "/submit", data={"telegram": "c1"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/freigabe"

        resp = await client.get("/freigabe")
        assert resp.status_code == 200
        assert "Hallo" in resp.text

        resp = await client.get("/freigabe/count")
        assert resp.status_code == 200
        assert '<span class="badge">1</span>' in resp.text

        resp = await client.post(
            f"/freigabe/drafts/{draft_id}/approve", data={"telegram": "c1"}
        )
        assert resp.status_code == 303
        post_id = f"diffus:{draft_id}"
        assert resp.headers["location"] == f"/posts/{post_id}"

        resp = await client.get(resp.headers["location"])
        assert resp.status_code == 200
        assert "Telegram c1 ✓" in resp.text  # multi_target: two chats configured (c1, c2)

    assert sink.calls == [(post_id, "c1")]


async def test_channel_auto_publish_switch_makes_a_compose_submit_publish_immediately(
    settings_env,
):
    uow = await make_uow()
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post("/channels", data={"auto": "telegram:c1"})
        assert resp.status_code == 303

        resp = await client.post(
            "/posts/new",
            data={"caption": "Direkt", "telegram": "c1"},
            files=[("images", ("a.png", ONE_BY_ONE_PNG, "image/png"))],
        )
        preview_url = resp.headers["location"]
        draft_id = preview_url.split("?")[0].rsplit("/", 1)[-1]

        resp = await client.get(preview_url)
        assert "Veröffentlichen" in resp.text

        resp = await client.post(preview_url.split("?")[0] + "/submit", data={"telegram": "c1"})
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/posts/diffus:{draft_id}"

    assert sink.calls == [(f"diffus:{draft_id}", "c1")]


async def test_compose_new_route_is_not_swallowed_by_the_post_detail_route(settings_env):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/posts/new")

    assert resp.status_code == 200
    assert "Post erstellen" in resp.text


async def test_compose_with_an_event_prefills_the_caption_and_links_the_post_after_publishing(
    settings_env,
):
    hint = ComposeHint(
        event_id="e1", title="Plenum", caption="Vorlage", detail_url="/calendar/events/e1"
    )
    events = FakeEventDirectory(hints={"e1": hint})
    uow = await make_uow()
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia(), events=events)
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.get("/posts/new?event=e1")
        assert resp.status_code == 200
        assert "Vorlage" in resp.text

        await client.post("/channels", data={"auto": "telegram:c1"})

        resp = await client.post(
            "/posts/new",
            data={"caption": "Vorlage", "telegram": "c1", "event": "e1"},
            files=[("images", ("a.png", ONE_BY_ONE_PNG, "image/png"))],
        )
        preview_url = resp.headers["location"]

        resp = await client.post(preview_url.split("?")[0] + "/submit", data={"telegram": "c1"})
        assert resp.status_code == 303

    assert events.links
    assert events.links[0][0] == "e1"


async def test_new_posts_compose_upload_over_the_image_limit_is_rejected_with_413(settings_env):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services)
    files = [("images", (f"{i}.png", b"x", "image/png")) for i in range(11)]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post("/posts/new", data={"caption": "Hallo"}, files=files)

    assert resp.status_code == 413
    assert "Höchstens 10 Bilder" in resp.text


async def test_set_channels_with_a_malformed_destination_is_rejected(settings_env):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post("/channels", data={"auto": "nonsense"})

    assert resp.status_code == 400


async def test_review_count_badge_requires_auth(settings_env):
    services = make_services(await make_uow(), FakeSink(), FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/freigabe/count")

    assert resp.status_code == 401


async def test_a_polled_post_with_auto_off_queues_for_freigabe_and_can_be_approved(settings_env):
    token = Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=datetime.now(UTC) + timedelta(days=60),
        refreshed_at=datetime.now(UTC),
        scopes=Token.PUBLISH_SCOPE,
    )
    uow = await make_uow()  # already holds post "p1", so the bootstrap (mark_seen_only) is done
    await uow.tokens.save(token)
    await uow.commit()
    new_post = Post(
        id="p2",
        source="instagram",
        caption="Neuer Post",
        permalink="https://instagram.com/p/p2/",
        media=(MediaItem(url="https://cdn.example.com/p2.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
    )
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia(), source=StaticSource([new_post]))
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post("/sync")
        assert resp.status_code == 303

        resp = await client.get("/freigabe")
        assert resp.status_code == 200
        assert "Von Instagram" in resp.text
        assert "Neuer Post" in resp.text

        resp = await client.post("/freigabe/posts/p2/approve", data={"telegram": "c1"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/posts/p2"

    assert sink.calls == [("p2", "c1")]


async def test_rejecting_a_draft_removes_it_from_freigabe(settings_env):
    uow = await make_uow()
    sink = FakeSink()
    services = make_services(uow, sink, FakeMedia())
    app = create_app(services=services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", auth=("u", "p")
    ) as client:
        resp = await client.post(
            "/posts/new",
            data={"caption": "Wird abgelehnt", "telegram": "c1"},
            files=[("images", ("a.png", ONE_BY_ONE_PNG, "image/png"))],
        )
        preview_url = resp.headers["location"]
        draft_id = preview_url.split("?")[0].rsplit("/", 1)[-1]

        resp = await client.post(preview_url.split("?")[0] + "/submit", data={"telegram": "c1"})
        assert resp.headers["location"] == "/freigabe"

        resp = await client.get("/freigabe")
        assert "Wird abgelehnt" in resp.text

        resp = await client.post(f"/freigabe/drafts/{draft_id}/reject")
        assert resp.status_code == 303

        resp = await client.get("/freigabe")
        assert "Wird abgelehnt" not in resp.text
