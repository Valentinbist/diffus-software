from __future__ import annotations

from datetime import UTC, datetime

from connector.application.sync_posts import SyncPosts
from connector.domain.entities import DeliveryStatus, MediaItem, MediaType, Post
from tests.fakes import FakeDeliveries, FakeMedia, FakePosts, FakeSink, StaticSource


def make_post(post_id: str, minute: int = 0) -> Post:
    return Post(
        id=post_id,
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, minute, tzinfo=UTC),
    )


def make_sync(source, sink, chat_ids=("chat1",)):
    posts = FakePosts()
    deliveries = FakeDeliveries()
    media = FakeMedia()
    sync = SyncPosts(
        source=source,
        posts=posts,
        deliveries=deliveries,
        media=media,
        sink=sink,
        chat_ids=list(chat_ids),
    )
    return sync, posts, deliveries


async def test_first_run_marks_skipped_and_never_calls_sink():
    post = make_post("p1")
    sink = FakeSink()
    sync, posts, deliveries = make_sync(StaticSource([post]), sink)

    report = await sync.run()

    assert report.fetched == 1
    assert report.new == 1
    assert report.skipped == 1
    assert report.sent == 0
    assert report.failed == 0
    assert sink.calls == []

    delivs = await deliveries.for_posts(["p1"])
    assert delivs["p1"][0].status == DeliveryStatus.SKIPPED


async def test_new_post_after_bootstrap_is_sent_exactly_once_across_two_runs():
    bootstrap_post = make_post("p1")
    new_post = make_post("p2", minute=1)
    sink = FakeSink()
    source = StaticSource([bootstrap_post])
    sync, posts, deliveries = make_sync(source, sink)

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

    delivs = await deliveries.for_posts(["p2"])
    assert delivs["p2"][0].status == DeliveryStatus.SENT


async def test_failing_sink_marks_failed_retries_then_stops_after_5_attempts():
    bootstrap_post = make_post("p1")
    target_post = make_post("p2", minute=1)
    sink = FakeSink(fail=True)
    source = StaticSource([bootstrap_post])
    sync, posts, deliveries = make_sync(source, sink)

    await sync.run()  # bootstrap: empty table -> SKIPPED, sink untouched
    assert sink.calls == []

    source.posts = [bootstrap_post, target_post]

    for expected_attempts in range(1, 6):
        report = await sync.run()
        assert report.failed == 1
        assert report.sent == 0

        delivs = await deliveries.for_posts(["p2"])
        row = delivs["p2"][0]
        assert row.status == DeliveryStatus.FAILED
        assert row.attempts == expected_attempts

    assert sink.calls.count(("p2", "chat1")) == 5

    # Attempts have hit the cap: claim() must refuse to hand out another try.
    report_final = await sync.run()
    assert report_final.failed == 0
    assert report_final.sent == 0
    assert sink.calls.count(("p2", "chat1")) == 5
