"""ResendDelivery: manual resend from the UI, deliberately bypassing the retry cap."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.resend_delivery import ResendDelivery
from diffus.crossposting.domain.entities import (
    Delivery,
    DeliveryStatus,
    Destination,
    MediaItem,
    MediaType,
    Post,
)
from diffus.crossposting.domain.errors import ConnectorError
from tests.crossposting.fakes import FakeMedia, FakeSink, FakeUnitOfWork

DEST = Destination("telegram", "chat1")


def make_post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


def make_resend(sink=None):
    uow = FakeUnitOfWork()
    deliver = DeliverPost(
        media=FakeMedia(), sinks={"telegram": sink if sink is not None else FakeSink()}, uow=uow
    )
    resend = ResendDelivery(uow=uow, deliver=deliver)
    return resend, uow


async def test_resend_unknown_post_raises_connector_error():
    resend, _uow = make_resend()

    with pytest.raises(ConnectorError):
        await resend.run("nope", DEST)


async def test_resend_success_keeps_attempts_and_records_sent():
    resend, uow = make_resend()
    await uow.posts.upsert(make_post())
    existing = Delivery(
        post_id="p1", destination=DEST, status=DeliveryStatus.FAILED, attempts=2, error="boom"
    )
    await uow.deliveries.save(existing)
    await uow.commit()

    status = await resend.run("p1", DEST)

    assert status == DeliveryStatus.SENT
    row = (await uow.deliveries.for_posts(["p1"]))["p1"][0]
    assert row.status == DeliveryStatus.SENT
    assert row.attempts == 2  # history kept, not reset
    assert row.error is None
    assert uow.commits >= 1


async def test_resend_failure_increments_attempts():
    resend, uow = make_resend(sink=FakeSink(fail=True))
    await uow.posts.upsert(make_post())
    existing = Delivery(post_id="p1", destination=DEST, status=DeliveryStatus.FAILED, attempts=2)
    await uow.deliveries.save(existing)
    await uow.commit()

    status = await resend.run("p1", DEST)

    assert status == DeliveryStatus.FAILED
    row = (await uow.deliveries.for_posts(["p1"]))["p1"][0]
    assert row.attempts == 3
    assert uow.commits >= 1


async def test_resend_bypasses_the_retry_cap():
    resend, uow = make_resend()
    await uow.posts.upsert(make_post())
    existing = Delivery(
        post_id="p1",
        destination=DEST,
        status=DeliveryStatus.FAILED,
        attempts=Delivery.MAX_ATTEMPTS,
    )
    assert not existing.can_retry()
    await uow.deliveries.save(existing)
    await uow.commit()

    status = await resend.run("p1", DEST)

    assert status == DeliveryStatus.SENT  # delivered despite the cap
    assert uow.commits >= 1


async def test_resend_with_no_prior_delivery_creates_and_commits_one():
    resend, uow = make_resend()
    await uow.posts.upsert(make_post())
    await uow.commit()

    status = await resend.run("p1", DEST)

    assert status == DeliveryStatus.SENT
    row = (await uow.deliveries.for_posts(["p1"]))["p1"][0]
    assert row.attempts == 0
    assert uow.commits >= 1
