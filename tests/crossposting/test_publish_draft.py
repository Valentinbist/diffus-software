"""PublishDraft: publish to Instagram, to Telegram, or both — and the no-duplicate guarantee."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.overview import NoEvents
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.application.sync_posts import SyncPosts
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    AccessToken,
    DeliveryStatus,
    Destination,
    DraftImage,
    DraftStatus,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    PublishTargets,
    Token,
)
from diffus.crossposting.domain.errors import DraftError, NotConnectedError
from diffus.crossposting.domain.ports import EventDirectory
from tests.crossposting.fakes import (
    FakeDrafts,
    FakeEventDirectory,
    FakeMedia,
    FakePublisher,
    FakeSink,
    FakeTokens,
    FakeUnitOfWork,
    StaticSource,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TELEGRAM = Destination("telegram", "chat1")
SIGNAL = Destination("signal", "chat2")


def make_draft(images: int = 2) -> PostDraft:
    return PostDraft.new(
        caption="Siebdruck-Nachmittag",
        images=[DraftImage("image/jpeg", 100, 100, f"img{i}".encode()) for i in range(images)],
        now=NOW,
    )


def make_token(can_publish: bool = True) -> Token:
    return Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=NOW + timedelta(days=60),
        refreshed_at=NOW,
        scopes=Token.PUBLISH_SCOPE if can_publish else "",
    )


async def seed(
    draft: PostDraft | None,
    token: Token | None = None,
    destinations: Sequence[Destination] = (TELEGRAM, SIGNAL),
    public_base_url: str = "https://example.com",
    publisher: FakePublisher | None = None,
    sinks: dict[str, FakeSink] | None = None,
    events: EventDirectory | None = None,
) -> tuple[PublishDraft, FakeUnitOfWork, dict[str, FakeSink]]:
    uow = FakeUnitOfWork(tokens=FakeTokens(token), drafts=FakeDrafts())
    if draft is not None:
        async with uow as u:
            await u.drafts.add(draft)
            await u.commit()
    sinks = sinks if sinks is not None else {"telegram": FakeSink(), "signal": FakeSink()}
    publish = PublishDraft(
        uow=uow,
        publisher=publisher if publisher is not None else FakePublisher(),
        sinks=sinks,
        destinations=list(destinations),
        public_base_url=public_base_url,
        events=events if events is not None else NoEvents(),
    )
    return publish, uow, sinks


# -- Instagram + Telegram --------------------------------------------------------


async def test_instagram_and_one_destination_stores_delivers_once_and_the_poller_does_not_resend():
    draft = make_draft(images=2)
    token = make_token()
    post = Post(
        id="ig-media-1",
        source="instagram",
        caption="Siebdruck-Nachmittag",
        permalink="https://instagram.com/p/ig-media-1/",
        media=(
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
            MediaItem(url="https://cdn.example.com/2.jpg", type=MediaType.IMAGE),
        ),
        posted_at=NOW,
    )
    publisher = FakePublisher(post=post)
    publish, uow, sinks = await seed(draft, token=token, publisher=publisher)

    result = await publish.run(draft.id, PublishTargets(instagram=True, destinations=(TELEGRAM,)))

    assert result.id == "ig-media-1"
    assert publisher.calls == [
        (
            [
                draft.public_media_url("https://example.com", 0),
                draft.public_media_url("https://example.com", 1),
            ],
            "Siebdruck-Nachmittag",
        )
    ]

    assert await uow.posts.get("ig-media-1") is not None
    for i in range(2):
        preview = await uow.previews.get("ig-media-1", i)
        assert preview is not None
        assert preview.data == f"img{i}".encode()

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.PUBLISHED
    assert stored_draft.post_id == "ig-media-1"

    delivs = await uow.deliveries.for_posts(["ig-media-1"])
    by_dest = {d.destination: d for d in delivs["ig-media-1"]}
    assert by_dest[TELEGRAM].status == DeliveryStatus.SENT
    assert by_dest[SIGNAL].status == DeliveryStatus.SKIPPED
    assert sinks["telegram"].calls == [("ig-media-1", "chat1")]
    assert sinks["signal"].calls == []

    # A later poll of the very same post must find nothing left to do.
    sync = SyncPosts(
        source=StaticSource([post]),
        media=FakeMedia(),
        deliver=DeliverPost(media=FakeMedia(), sinks=sinks, uow=uow),
        destinations=[TELEGRAM, SIGNAL],
        uow=uow,
    )
    await sync.run()

    assert sinks["telegram"].calls == [("ig-media-1", "chat1")]
    assert sinks["signal"].calls == []


# -- Telegram only ----------------------------------------------------------------


async def test_telegram_only_uses_the_diffus_post_id_and_an_empty_permalink():
    draft = make_draft(images=1)
    publish, uow, sinks = await seed(draft, token=None, destinations=(TELEGRAM,))

    result = await publish.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))

    assert result.id == f"diffus:{draft.id}"
    assert result.source == "diffus"
    assert result.permalink == ""

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.PUBLISHED
    assert stored_draft.post_id == result.id

    assert await uow.previews.get(result.id, 0) is not None

    delivs = await uow.deliveries.for_posts([result.id])
    assert delivs[result.id][0].status == DeliveryStatus.SENT
    assert sinks["telegram"].calls == [(result.id, "chat1")]


# -- refusals -----------------------------------------------------------------------


async def test_an_unknown_draft_is_refused():
    publish, _, _ = await seed(None)

    with pytest.raises(DraftError, match="Entwurf nicht gefunden"):
        await publish.run("nope", PublishTargets(instagram=False, destinations=(TELEGRAM,)))


async def test_an_already_published_draft_is_refused():
    draft = make_draft()
    draft.mark_published("p-old", NOW)
    publish, _, _ = await seed(draft)

    with pytest.raises(DraftError, match="schon veröffentlicht"):
        await publish.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))


async def test_choosing_no_target_at_all_is_refused():
    draft = make_draft()
    publish, _, _ = await seed(draft)

    with pytest.raises(DraftError, match="Mindestens ein Ziel"):
        await publish.run(draft.id, PublishTargets(instagram=False, destinations=()))


async def test_instagram_without_a_connected_token_is_refused():
    draft = make_draft()
    publish, _, _ = await seed(draft, token=None)

    with pytest.raises(NotConnectedError):
        await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))


async def test_instagram_with_a_token_missing_the_publish_scope_is_refused():
    draft = make_draft()
    publish, _, _ = await seed(draft, token=make_token(can_publish=False))

    with pytest.raises(DraftError, match="neu verbinden"):
        await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))


async def test_instagram_without_a_public_https_base_url_is_refused():
    draft = make_draft()
    publish, _, _ = await seed(
        draft, token=make_token(), public_base_url="http://localhost:8000"
    )

    with pytest.raises(DraftError, match="https"):
        await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))


# -- publisher failure ---------------------------------------------------------------


async def test_a_publisher_failure_marks_the_draft_failed_and_writes_no_post():
    draft = make_draft()
    publisher = FakePublisher(fail=RuntimeError("meta is down"))
    publish, uow, _ = await seed(draft, token=make_token(), publisher=publisher)

    with pytest.raises(RuntimeError, match="meta is down"):
        await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.FAILED
    assert stored_draft.error == "meta is down"
    assert await uow.posts.count() == 0


# -- Freigabe: the Instagram delivery record, source, targets, event linking -----


def make_instagram_post(post_id: str = "ig-media-1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="Siebdruck-Nachmittag",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),),
        posted_at=NOW,
    )


async def test_the_instagram_leg_records_a_sent_delivery_to_the_instagram_channel():
    draft = make_draft(images=1)
    publisher = FakePublisher(post=make_instagram_post())
    publish, uow, _sinks = await seed(
        draft, token=make_token(), publisher=publisher, destinations=()
    )

    result = await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))

    delivs = await uow.deliveries.for_posts([result.id])
    by_dest = {d.destination: d for d in delivs[result.id]}
    assert by_dest[INSTAGRAM_CHANNEL].status == DeliveryStatus.SENT
    assert by_dest[INSTAGRAM_CHANNEL].sent_at is not None


async def test_source_diffus_survives_a_later_poller_upsert_of_the_instagram_post():
    draft = make_draft(images=1)
    instagram_post = make_instagram_post()
    publisher = FakePublisher(post=instagram_post)
    publish, uow, _sinks = await seed(
        draft, token=make_token(), publisher=publisher, destinations=()
    )

    result = await publish.run(draft.id, PublishTargets(instagram=True, destinations=()))
    assert result.source == "diffus"

    # A later poll fetches the same post from Instagram itself (source="instagram")
    # and upserts it; on_conflict_do_nothing must leave the stored row untouched.
    await uow.posts.upsert(instagram_post)
    await uow.commit()

    stored = await uow.posts.get(result.id)
    assert stored is not None
    assert stored.source == "diffus"


async def test_run_without_targets_uses_the_drafts_own_stored_targets():
    draft = make_draft(images=1)
    draft.status = DraftStatus.FAILED
    draft.targets = PublishTargets(instagram=False, destinations=(TELEGRAM,))
    publish, uow, sinks = await seed(draft)

    result = await publish.run(draft.id)  # no targets argument at all

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.PUBLISHED
    assert sinks["telegram"].calls == [(result.id, "chat1")]


@pytest.mark.parametrize("status", [DraftStatus.REVIEW, DraftStatus.FAILED])
async def test_review_and_failed_drafts_can_be_published(status):
    draft = make_draft(images=1)
    draft.status = status
    publish, uow, _sinks = await seed(draft)

    await publish.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.PUBLISHED


async def test_a_target_destination_not_configured_is_refused():
    draft = make_draft()
    publish, _uow, _sinks = await seed(draft, destinations=(TELEGRAM,))

    with pytest.raises(DraftError, match="Unbekanntes Ziel"):
        await publish.run(draft.id, PublishTargets(instagram=False, destinations=(SIGNAL,)))


async def test_publishing_a_draft_started_from_an_event_links_the_post_back():
    draft = make_draft(images=1)
    draft.event_ref = "calendar:e1"
    events = FakeEventDirectory()
    publish, _uow, _sinks = await seed(draft, events=events)

    result = await publish.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))

    assert events.links == [("e1", result.id)]


class _RaisingEventDirectory:
    """EventDirectory whose link() always fails, the way a calendar outage would."""

    async def for_posts(self, post_ids):
        return {}

    async def compose_hint(self, event_id):
        return None

    async def link(self, event_id, post_id):
        raise RuntimeError("calendar is down")


async def test_a_failed_event_link_is_logged_but_the_post_still_publishes(caplog):
    draft = make_draft(images=1)
    draft.event_ref = "calendar:e1"
    publish, uow, _sinks = await seed(draft, events=_RaisingEventDirectory())

    with caplog.at_level("ERROR"):
        result = await publish.run(
            draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,))
        )

    stored_draft = await uow.drafts.get(draft.id)
    assert stored_draft is not None
    assert stored_draft.status == DraftStatus.PUBLISHED
    assert stored_draft.post_id == result.id
    assert "failed to link" in caplog.text
