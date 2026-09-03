from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.sync_posts import SyncPosts
from diffus.crossposting.domain.entities import (
    AccessToken,
    DeliveryStatus,
    Destination,
    MediaItem,
    MediaType,
    Post,
    Token,
)
from diffus.crossposting.domain.errors import NotConnectedError
from tests.crossposting.fakes import FakeMedia, FakeSink, FakeTokens, FakeUnitOfWork, StaticSource


def make_post(post_id: str, minute: int = 0, media: tuple[MediaItem, ...] | None = None) -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=media
        or (MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, minute, tzinfo=UTC),
    )


def make_token() -> Token:
    now = datetime.now(UTC)
    return Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=now + timedelta(days=60),
        refreshed_at=now,
    )


DEFAULT_DESTINATIONS = (Destination("telegram", "chat1"),)


def make_sync(source, sink, destinations=DEFAULT_DESTINATIONS, media=None):
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    media_gateway = media if media is not None else FakeMedia()
    deliver = DeliverPost(media=media_gateway, sinks={"telegram": sink}, uow=uow)
    sync = SyncPosts(
        source=source,
        media=media_gateway,
        deliver=deliver,
        destinations=list(destinations),
        uow=uow,
    )
    return sync, uow


async def test_first_run_marks_skipped_and_never_calls_sink():
    post = make_post("p1")
    sink = FakeSink()
    sync, uow = make_sync(StaticSource([post]), sink)

    report = await sync.run()

    assert report.fetched == 1
    assert report.new == 1
    assert report.skipped == 1
    assert report.sent == 0
    assert report.failed == 0
    assert sink.calls == []

    delivs = await uow.deliveries.for_posts(["p1"])
    assert delivs["p1"][0].status == DeliveryStatus.SKIPPED


async def test_missing_token_raises_not_connected_and_fetches_nothing():
    sink = FakeSink()
    source = StaticSource([make_post("p1")])
    uow = FakeUnitOfWork()  # no token seeded
    media = FakeMedia()
    deliver = DeliverPost(media=media, sinks={"telegram": sink}, uow=uow)
    sync = SyncPosts(
        source=source,
        media=media,
        deliver=deliver,
        destinations=[Destination("telegram", "chat1")],
        uow=uow,
    )

    with pytest.raises(NotConnectedError):
        await sync.run()

    assert sink.calls == []


async def test_new_post_after_bootstrap_is_sent_exactly_once_across_two_runs():
    bootstrap_post = make_post("p1")
    new_post = make_post("p2", minute=1)
    sink = FakeSink()
    source = StaticSource([bootstrap_post])
    sync, uow = make_sync(source, sink)

    # Bootstrap run: table starts empty -> everything SKIPPED, nothing sent.
    await sync.run()
    assert sink.calls == []

    # A new post shows up on the next poll.
    source.posts = [bootstrap_post, new_post]
    report2 = await sync.run()

    assert report2.sent == 1
    assert sink.calls == [("p2", "chat1")]

    # Polling again must not resend an already-SENT delivery.
    report3 = await sync.run()
    assert report3.sent == 0
    assert sink.calls == [("p2", "chat1")]

    delivs = await uow.deliveries.for_posts(["p2"])
    assert delivs["p2"][0].status == DeliveryStatus.SENT


async def test_failing_sink_marks_failed_retries_then_stops_after_5_attempts():
    bootstrap_post = make_post("p1")
    target_post = make_post("p2", minute=1)
    sink = FakeSink(fail=True)
    source = StaticSource([bootstrap_post])
    sync, uow = make_sync(source, sink)

    await sync.run()  # bootstrap: empty table -> SKIPPED, sink untouched
    assert sink.calls == []

    source.posts = [bootstrap_post, target_post]

    for expected_attempts in range(1, 6):
        report = await sync.run()
        assert report.failed == 1
        assert report.sent == 0

        delivs = await uow.deliveries.for_posts(["p2"])
        row = delivs["p2"][0]
        assert row.status == DeliveryStatus.FAILED
        assert row.attempts == expected_attempts

    assert sink.calls.count(("p2", "chat1")) == 5

    # Attempts have hit the cap: claim() must refuse to hand out another try.
    report_final = await sync.run()
    assert report_final.failed == 0
    assert report_final.sent == 0
    assert sink.calls.count(("p2", "chat1")) == 5


# -- previews: the UI's images, stored while the CDN links are fresh ----------


async def test_every_still_image_is_stored_once_even_on_the_bootstrap_run():
    post = make_post(
        "p1",
        media=(
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
            MediaItem(
                url="https://cdn.example.com/2.mp4",
                type=MediaType.VIDEO,
                thumbnail_url="https://cdn.example.com/2-thumb.jpg",
            ),
        ),
    )
    media = FakeMedia(
        images={
            "https://cdn.example.com/1.jpg": b"one",
            "https://cdn.example.com/2-thumb.jpg": b"two",
        }
    )
    sync, uow = make_sync(StaticSource([post]), FakeSink(), media=media)

    report = await sync.run()  # bootstrap run: nothing is sent, but previews are still kept
    await sync.run()

    assert report.previews == 2
    assert await uow.previews.stored(["p1"]) == {"p1": frozenset({0, 1})}
    assert (await uow.previews.get("p1", 1)).data == b"two"
    assert sorted(media.downloads) == [
        "https://cdn.example.com/1.jpg",
        "https://cdn.example.com/2-thumb.jpg",
    ]  # the second run downloaded nothing


async def test_video_without_a_still_frame_is_not_downloaded():
    post = make_post(
        "p1", media=(MediaItem(url="https://cdn.example.com/1.mp4", type=MediaType.VIDEO),)
    )
    media = FakeMedia()
    sync, uow = make_sync(StaticSource([post]), FakeSink(), media=media)

    await sync.run()

    assert media.downloads == []
    assert await uow.previews.stored(["p1"]) == {}


async def test_preview_download_failure_never_blocks_delivery():
    bootstrap_post = make_post("p1")
    new_post = make_post("p2", minute=1)
    sink = FakeSink()
    source = StaticSource([bootstrap_post])
    sync, uow = make_sync(source, sink, media=FakeMedia(fail_images=True))

    await sync.run()
    source.posts = [bootstrap_post, new_post]
    report = await sync.run()

    assert report.sent == 1
    assert sink.calls == [("p2", "chat1")]
    assert report.previews == 0
    assert await uow.previews.stored(["p1", "p2"]) == {}


# -- sink registry --------------------------------------------------------------


async def test_two_sinks_with_the_same_address_get_separate_deliveries():
    bootstrap_post = make_post("p1")
    new_post = make_post("p2", minute=1)
    telegram_sink = FakeSink()
    signal_sink = FakeSink()
    source = StaticSource([bootstrap_post])
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    media = FakeMedia()
    deliver = DeliverPost(
        media=media, sinks={"telegram": telegram_sink, "signal": signal_sink}, uow=uow
    )
    sync = SyncPosts(
        source=source,
        media=media,
        deliver=deliver,
        destinations=[Destination("telegram", "x"), Destination("signal", "x")],
        uow=uow,
    )

    await sync.run()  # bootstrap: empty table -> SKIPPED, sinks untouched
    source.posts = [bootstrap_post, new_post]
    report = await sync.run()

    assert report.sent == 2
    assert telegram_sink.calls == [("p2", "x")]
    assert signal_sink.calls == [("p2", "x")]

    delivs = await uow.deliveries.for_posts(["p2"])
    assert {d.destination for d in delivs["p2"]} == {
        Destination("telegram", "x"),
        Destination("signal", "x"),
    }


async def test_unknown_sink_is_recorded_as_failed_and_does_not_stop_the_loop():
    bootstrap_post = make_post("p1")
    new_post = make_post("p2", minute=1)
    source = StaticSource([bootstrap_post])
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    media = FakeMedia()
    deliver = DeliverPost(media=media, sinks={"telegram": FakeSink()}, uow=uow)
    sync = SyncPosts(
        source=source,
        media=media,
        deliver=deliver,
        destinations=[Destination("signal", "x"), Destination("telegram", "y")],
        uow=uow,
    )

    await sync.run()  # bootstrap: empty table -> SKIPPED
    source.posts = [bootstrap_post, new_post]
    report = await sync.run()  # must not raise despite the unknown sink

    assert report.failed == 1
    assert report.sent == 1

    delivs = await uow.deliveries.for_posts(["p2"])
    by_dest = {d.destination: d for d in delivs["p2"]}
    signal_delivery = by_dest[Destination("signal", "x")]
    assert signal_delivery.status == DeliveryStatus.FAILED
    assert signal_delivery.error is not None and "no sink" in signal_delivery.error
    assert by_dest[Destination("telegram", "y")].status == DeliveryStatus.SENT
