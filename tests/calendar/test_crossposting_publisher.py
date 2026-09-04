"""CrosspostingPublisher: the calendar's PostPublisher adapter over the real
crossposting use cases (CreateDraft, PublishDraft, GetPublishReadiness, GetDraft,
DiscardDraft), driven on crossposting's own fakes — no DB, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diffus.calendar.domain.entities import DraftRef, InstagramState, TelegramTarget
from diffus.calendar.domain.errors import PublishError
from diffus.calendar.infrastructure.crossposting import CrosspostingPublisher
from diffus.crossposting.application.drafts import CreateDraft, DiscardDraft, GetDraft
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.application.publish_readiness import GetPublishReadiness
from diffus.crossposting.domain.entities import AccessToken, Destination, Token
from tests.crossposting.fakes import FakeImageProcessor, FakeSink, FakeTokens, FakeUnitOfWork
from tests.crossposting.fakes import FakePublisher as FakeMediaPublisher

SOURCE = "instagram"


def make_token(scopes: str = Token.PUBLISH_SCOPE) -> Token:
    now = datetime.now(UTC)
    return Token(
        source=SOURCE,
        access_token=AccessToken("x"),
        external_user_id="1",
        expires_at=now + timedelta(days=60),
        refreshed_at=now,
        scopes=scopes,
    )


def make_publisher(
    uow: FakeUnitOfWork,
    destinations: list[Destination] | None = None,
    public_base_url: str = "https://example.com",
) -> CrosspostingPublisher:
    destinations = destinations if destinations is not None else [Destination("telegram", "c1")]
    return CrosspostingPublisher(
        create=CreateDraft(uow=uow, images=FakeImageProcessor()),
        publish_draft=PublishDraft(
            # These tests only ever choose Telegram, so the Instagram media
            # publisher fake is never actually called.
            uow=uow,
            publisher=FakeMediaPublisher(),
            sinks={"telegram": FakeSink()},
            destinations=destinations,
            public_base_url=public_base_url,
        ),
        readiness=GetPublishReadiness(uow=uow, source=SOURCE, public_base_url=public_base_url),
        drafts=GetDraft(uow=uow),
        discard_draft=DiscardDraft(uow=uow),
        destinations=destinations,
    )


async def test_create_draft_returns_a_draft_ref_with_the_new_drafts_id():
    uow = FakeUnitOfWork()
    publisher = make_publisher(uow)

    ref = await publisher.create_draft("Hallo", [("a.png", b"data")])

    assert isinstance(ref, DraftRef)
    stored = await uow.drafts.get(ref.id)
    assert stored is not None
    assert stored.caption == "Hallo"


async def test_create_draft_wraps_a_connector_error_as_the_calendars_publish_error():
    uow = FakeUnitOfWork()
    publisher = make_publisher(uow)

    with pytest.raises(PublishError):
        await publisher.create_draft("Hallo", [])  # no images: CreateDraft rejects it


async def test_get_draft_returns_a_preview_with_the_calendars_own_media_urls():
    uow = FakeUnitOfWork()
    publisher = make_publisher(uow)
    ref = await publisher.create_draft("Hallo", [("a.png", b"data")])

    preview = await publisher.get_draft(ref.id)

    assert preview is not None
    assert preview.caption == "Hallo"
    assert preview.image_urls == (f"/drafts/{ref.id}/media/0",)


async def test_get_draft_returns_none_for_an_unknown_draft():
    publisher = make_publisher(FakeUnitOfWork())

    assert await publisher.get_draft("nope") is None


async def test_publish_returns_a_published_post_whose_detail_url_is_built_from_its_id():
    uow = FakeUnitOfWork()
    publisher = make_publisher(uow)
    ref = await publisher.create_draft("Hallo", [("a.png", b"data")])

    published = await publisher.publish(ref.id, False, ["c1"])

    assert published.id.startswith("diffus:")
    assert published.detail_url == f"/posts/{published.id}"


async def test_publish_wraps_a_connector_error_as_the_calendars_publish_error():
    publisher = make_publisher(FakeUnitOfWork())

    with pytest.raises(PublishError):
        await publisher.publish("no-such-draft", False, ["c1"])


async def test_discard_removes_the_draft():
    uow = FakeUnitOfWork()
    publisher = make_publisher(uow)
    ref = await publisher.create_draft("Hallo", [("a.png", b"data")])

    await publisher.discard(ref.id)

    assert await uow.drafts.get(ref.id) is None


# -- options(): the four InstagramState mappings -----------------------------


async def test_options_reports_not_connected_when_there_is_no_token():
    uow = FakeUnitOfWork(tokens=FakeTokens())
    publisher = make_publisher(uow)

    options = await publisher.options()

    assert options.instagram == InstagramState.NOT_CONNECTED


async def test_options_reports_no_publish_scope_for_a_token_without_it():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token(scopes="")))
    publisher = make_publisher(uow)

    options = await publisher.options()

    assert options.instagram == InstagramState.NO_PUBLISH_SCOPE


async def test_options_reports_no_public_url_when_public_base_url_is_not_https():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    publisher = make_publisher(uow, public_base_url="http://localhost:8000")

    options = await publisher.options()

    assert options.instagram == InstagramState.NO_PUBLIC_URL


async def test_options_reports_ready_when_connected_scoped_and_public():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    publisher = make_publisher(uow)

    options = await publisher.options()

    assert options.instagram == InstagramState.READY


async def test_options_labels_a_single_destination_plainly():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    publisher = make_publisher(uow, destinations=[Destination("telegram", "c1")])

    options = await publisher.options()

    assert options.targets == (TelegramTarget(address="c1", label="Telegram"),)


async def test_options_labels_multiple_destinations_by_address():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    destinations = [Destination("telegram", "c1"), Destination("telegram", "c2")]
    publisher = make_publisher(uow, destinations=destinations)

    options = await publisher.options()

    assert options.targets == (
        TelegramTarget(address="c1", label="Telegram c1"),
        TelegramTarget(address="c2", label="Telegram c2"),
    )
