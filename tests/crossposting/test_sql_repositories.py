"""SqlDeliveryRepository, SqlDraftRepository and SqlChannelSettingsRepository against Postgres.

Everything else in this context is tested against the in-memory fakes; this
file exists for the handful of behaviours that are genuinely SQL — `claim`'s
`INSERT ... ON CONFLICT ... RETURNING`, the JSONB round trip of
`post_drafts.targets`, and the FK ordering `SqlDraftRepository.add` depends
on (the draft row must be flushed before its media rows — see that method's
own docstring). Skipped unless `TEST_DATABASE_URL` is set; run it inside the
compose network against a disposable `connector_test` database, never the
dev `connector` one — see the round 3 hand-off's runbook for the exact
`docker compose` invocations.
"""

from __future__ import annotations

import functools
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from diffus.crossposting.domain.entities import (
    Destination,
    DraftImage,
    DraftStatus,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
    PublishTargets,
)
from diffus.crossposting.infrastructure.db.uow import SqlUnitOfWork
from diffus.shared.db.session import make_engine, make_session_factory

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to run this against a real Postgres"
)

# Crossposting's own tables only — calendar tables are a separate context's
# schema and are never touched here (see docs/architecture.md, rule 3).
TABLES = "deliveries, previews, posts, post_draft_media, post_drafts, channel_settings, tokens"


@pytest.fixture
async def factory():
    """A fresh UnitOfWorkFactory per test, against a table set truncated just before it runs."""
    assert TEST_DATABASE_URL is not None
    engine = make_engine(TEST_DATABASE_URL)
    session_factory = make_session_factory(engine)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {TABLES} RESTART IDENTITY CASCADE"))
    try:
        yield functools.partial(SqlUnitOfWork, session_factory)
    finally:
        await engine.dispose()


def make_post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


def make_draft(
    caption: str = "Hallo",
    created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    event_ref: str | None = None,
    images: int = 1,
) -> PostDraft:
    return PostDraft.new(
        caption,
        [DraftImage("image/jpeg", 10, 10, f"img{i}".encode()) for i in range(images)],
        created_at,
        event_ref=event_ref,
    )


# -- SqlDeliveryRepository: Freigabe ---------------------------------------------


async def test_claim_refuses_a_row_waiting_in_review(factory):
    dest = Destination("telegram", "c1")
    async with factory() as uow:
        await uow.posts.upsert(make_post())
        delivery = await uow.deliveries.claim("p1", dest)
        assert delivery is not None
        delivery.queue_for_review()
        await uow.deliveries.save(delivery)
        await uow.commit()

    async with factory() as uow:
        claimed = await uow.deliveries.claim("p1", dest)

    assert claimed is None


async def test_in_review_groups_by_post_and_count_posts_in_review_counts_distinct_posts(factory):
    async with factory() as uow:
        await uow.posts.upsert(make_post("p1"))
        await uow.posts.upsert(make_post("p2"))
        for post_id, dest in [
            ("p1", Destination("telegram", "c1")),
            ("p1", Destination("signal", "c2")),
            ("p2", Destination("telegram", "c1")),
        ]:
            delivery = await uow.deliveries.claim(post_id, dest)
            assert delivery is not None
            delivery.queue_for_review()
            await uow.deliveries.save(delivery)
        await uow.commit()

    async with factory() as uow:
        in_review = await uow.deliveries.in_review()
        count = await uow.deliveries.count_posts_in_review()

    assert set(in_review) == {"p1", "p2"}
    assert len(in_review["p1"]) == 2
    assert len(in_review["p2"]) == 1
    assert count == 2


# -- SqlDraftRepository: targets/event_ref, the Freigabe queue, the FK lesson ----


async def test_add_flushes_the_draft_row_before_its_media_rows(factory):
    """The FK lesson from 0005: without it, post_draft_media_draft_id_fkey fails."""
    draft = make_draft(images=3)

    async with factory() as uow:
        await uow.drafts.add(draft)
        await uow.commit()

    async with factory() as uow:
        stored = await uow.drafts.get(draft.id)

    assert stored is not None
    assert [img.data for img in stored.images] == [b"img0", b"img1", b"img2"]


async def test_targets_and_event_ref_round_trip_through_add_and_get(factory):
    targets = PublishTargets(instagram=True, destinations=(Destination("telegram", "c1"),))
    draft = make_draft(event_ref="calendar:e1")
    draft.submit_for_review(targets)

    async with factory() as uow:
        await uow.drafts.add(draft)
        await uow.commit()

    async with factory() as uow:
        stored = await uow.drafts.get(draft.id)

    assert stored is not None
    assert stored.status == DraftStatus.REVIEW
    assert stored.event_ref == "calendar:e1"
    assert stored.targets == targets


async def test_a_draft_added_without_targets_or_event_ref_reads_back_as_none(factory):
    draft = make_draft()

    async with factory() as uow:
        await uow.drafts.add(draft)
        await uow.commit()

    async with factory() as uow:
        stored = await uow.drafts.get(draft.id)

    assert stored is not None
    assert stored.targets is None
    assert stored.event_ref is None


async def test_update_persists_targets_alongside_status(factory):
    draft = make_draft()
    async with factory() as uow:
        await uow.drafts.add(draft)
        await uow.commit()

    targets = PublishTargets(instagram=False, destinations=(Destination("telegram", "c1"),))
    draft.submit_for_review(targets)
    async with factory() as uow:
        await uow.drafts.update(draft)
        await uow.commit()

    async with factory() as uow:
        stored = await uow.drafts.get(draft.id)

    assert stored is not None
    assert stored.status == DraftStatus.REVIEW
    assert stored.targets == draft.targets


async def test_in_review_lists_review_and_failed_drafts_ordered_by_created_at(factory):
    targets = PublishTargets(instagram=False, destinations=(Destination("telegram", "c1"),))
    old = make_draft(caption="Old", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    old.submit_for_review(targets)
    newer = make_draft(caption="New", created_at=datetime(2026, 1, 2, tzinfo=UTC))
    newer.targets = targets
    newer.mark_failed("boom")
    plain = make_draft(caption="Plain", created_at=datetime(2026, 1, 3, tzinfo=UTC))

    async with factory() as uow:
        await uow.drafts.add(old)
        await uow.drafts.add(newer)
        await uow.drafts.add(plain)
        await uow.commit()

    async with factory() as uow:
        in_review = await uow.drafts.in_review()
        count = await uow.drafts.count_in_review()

    assert [d.id for d in in_review] == [old.id, newer.id]
    assert count == 2


# -- SqlChannelSettingsRepository -------------------------------------------------


async def test_get_all_is_empty_before_any_channel_is_touched(factory):
    async with factory() as uow:
        assert await uow.channels.get_all() == {}


async def test_set_upserts_rather_than_duplicating(factory):
    telegram = Destination("telegram", "c1")
    instagram = Destination("instagram", "account")

    async with factory() as uow:
        await uow.channels.set(telegram, True)
        await uow.channels.set(instagram, False)
        await uow.commit()

    async with factory() as uow:
        assert await uow.channels.get_all() == {telegram: True, instagram: False}
        await uow.channels.set(telegram, False)  # same key again: update, not a new row
        await uow.commit()

    async with factory() as uow:
        settings = await uow.channels.get_all()

    assert settings == {telegram: False, instagram: False}
