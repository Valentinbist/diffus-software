"""GetReviewQueue, CountReview, ApprovePostDeliveries and RejectPostDeliveries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.review import (
    ApprovePostDeliveries,
    CountReview,
    GetReviewQueue,
    RejectPostDeliveries,
)
from diffus.crossposting.domain.entities import (
    ComposeHint,
    Delivery,
    DeliveryStatus,
    Destination,
    DraftImage,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    PublishTargets,
)
from diffus.crossposting.domain.errors import ConnectorError
from tests.crossposting.fakes import FakeEventDirectory, FakeMedia, FakeSink, FakeUnitOfWork

TELEGRAM = Destination("telegram", "c1")
SIGNAL = Destination("signal", "c2")


def make_post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


async def make_uow_with_review_post(
    post_id: str = "p1", destinations: Sequence[Destination] = (TELEGRAM, SIGNAL)
) -> FakeUnitOfWork:
    uow = FakeUnitOfWork()
    await uow.posts.upsert(make_post(post_id))
    for dest in destinations:
        delivery = Delivery(post_id=post_id, destination=dest)
        delivery.queue_for_review()
        await uow.deliveries.save(delivery)
    await uow.commit()
    return uow


def make_reviewable_draft(event_ref: str | None = None) -> PostDraft:
    draft = PostDraft.new(
        "Hallo",
        [DraftImage("image/jpeg", 1, 1, b"x")],
        datetime.now(UTC),
        event_ref=event_ref,
    )
    draft.submit_for_review(PublishTargets(instagram=False, destinations=(TELEGRAM,)))
    return draft


# -- GetReviewQueue: drafts -----------------------------------------------------


async def test_review_queue_lists_a_reviewable_draft_with_its_image_urls():
    uow = FakeUnitOfWork()
    draft = make_reviewable_draft()
    await uow.drafts.add(draft)
    await uow.commit()
    queue = GetReviewQueue(
        uow=uow, detail=GetPostDetail(uow=uow), events=FakeEventDirectory(), destinations=[TELEGRAM]
    )

    result = await queue.run()

    assert len(result.drafts) == 1
    assert result.drafts[0].draft.id == draft.id
    assert result.drafts[0].image_urls == (f"/drafts/{draft.id}/media/0",)
    assert result.drafts[0].hint is None


async def test_review_queue_attaches_the_compose_hint_for_an_event_linked_draft():
    uow = FakeUnitOfWork()
    draft = make_reviewable_draft(event_ref="calendar:e1")
    await uow.drafts.add(draft)
    await uow.commit()
    hint = ComposeHint(
        event_id="e1", title="Plenum", caption="Text", detail_url="/calendar/events/e1"
    )
    events = FakeEventDirectory(hints={"e1": hint})
    queue = GetReviewQueue(
        uow=uow, detail=GetPostDetail(uow=uow), events=events, destinations=[TELEGRAM]
    )

    result = await queue.run()

    assert result.drafts[0].hint == hint


# -- GetReviewQueue: posts -------------------------------------------------------


async def test_review_queue_lists_a_post_and_proposes_only_configured_destinations():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM, SIGNAL))
    queue = GetReviewQueue(
        uow=uow, detail=GetPostDetail(uow=uow), events=FakeEventDirectory(), destinations=[TELEGRAM]
    )

    result = await queue.run()

    assert len(result.posts) == 1
    assert result.posts[0].view.post.id == "p1"
    assert result.posts[0].proposed == [TELEGRAM]  # SIGNAL has a REVIEW row but isn't configured


# -- CountReview ------------------------------------------------------------------


async def test_count_review_counts_drafts_plus_distinct_posts():
    uow = await make_uow_with_review_post(post_id="p1", destinations=(TELEGRAM, SIGNAL))
    await uow.drafts.add(make_reviewable_draft())
    await uow.commit()

    count = await CountReview(uow=uow).run()

    assert count == 2  # one draft, one post (its two REVIEW rows count once)


async def test_count_review_is_zero_when_nothing_is_queued():
    assert await CountReview(uow=FakeUnitOfWork()).run() == 0


# -- ApprovePostDeliveries ---------------------------------------------------------


async def test_approve_sends_the_chosen_destination_and_rejects_the_rest():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM, SIGNAL))
    telegram_sink, signal_sink = FakeSink(), FakeSink()
    deliver = DeliverPost(
        media=FakeMedia(), sinks={"telegram": telegram_sink, "signal": signal_sink}, uow=uow
    )
    approve = ApprovePostDeliveries(uow=uow, deliver=deliver, destinations=[TELEGRAM, SIGNAL])

    statuses = await approve.run("p1", [TELEGRAM])

    assert statuses == [DeliveryStatus.SENT]
    assert telegram_sink.calls == [("p1", "c1")]
    assert signal_sink.calls == []
    delivs = await uow.deliveries.for_posts(["p1"])
    by_dest = {d.destination: d for d in delivs["p1"]}
    assert by_dest[TELEGRAM].status == DeliveryStatus.SENT
    assert by_dest[SIGNAL].status == DeliveryStatus.SKIPPED


async def test_a_later_poll_sends_nothing_after_approval():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM,))
    sink = FakeSink()
    deliver = DeliverPost(media=FakeMedia(), sinks={"telegram": sink}, uow=uow)
    approve = ApprovePostDeliveries(uow=uow, deliver=deliver, destinations=[TELEGRAM])
    await approve.run("p1", [TELEGRAM])

    claimed = await uow.deliveries.claim("p1", TELEGRAM)  # what a later poll would call

    assert claimed is None  # already SENT, not retryable
    assert sink.calls == [("p1", "c1")]


async def test_a_second_approve_call_finds_no_review_rows_left():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM,))
    sink = FakeSink()
    deliver = DeliverPost(media=FakeMedia(), sinks={"telegram": sink}, uow=uow)
    approve = ApprovePostDeliveries(uow=uow, deliver=deliver, destinations=[TELEGRAM])
    await approve.run("p1", [TELEGRAM])

    statuses = await approve.run("p1", [TELEGRAM])

    assert statuses == []
    assert sink.calls == [("p1", "c1")]  # unchanged: no second send


async def test_a_chosen_but_unconfigured_destination_is_rejected_not_sent():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM,))
    sink = FakeSink()
    deliver = DeliverPost(media=FakeMedia(), sinks={"telegram": sink}, uow=uow)
    # TELEGRAM was queued, but is no longer in the configured destinations.
    approve = ApprovePostDeliveries(uow=uow, deliver=deliver, destinations=[])

    statuses = await approve.run("p1", [TELEGRAM])

    assert statuses == []
    assert sink.calls == []
    delivs = await uow.deliveries.for_posts(["p1"])
    assert delivs["p1"][0].status == DeliveryStatus.SKIPPED


async def test_approve_raises_for_an_unknown_post():
    uow = FakeUnitOfWork()
    deliver = DeliverPost(media=FakeMedia(), sinks={}, uow=uow)
    approve = ApprovePostDeliveries(uow=uow, deliver=deliver, destinations=[TELEGRAM])

    with pytest.raises(ConnectorError, match="Unbekannter Post"):
        await approve.run("nope", [TELEGRAM])


# -- RejectPostDeliveries -----------------------------------------------------------


async def test_reject_post_deliveries_rejects_every_review_row():
    uow = await make_uow_with_review_post(destinations=(TELEGRAM, SIGNAL))

    await RejectPostDeliveries(uow=uow).run("p1")

    delivs = await uow.deliveries.for_posts(["p1"])
    assert all(d.status == DeliveryStatus.SKIPPED for d in delivs["p1"])


async def test_reject_post_deliveries_on_an_unknown_post_does_nothing():
    uow = FakeUnitOfWork()

    await RejectPostDeliveries(uow=uow).run("nope")  # must not raise
