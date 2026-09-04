"""SubmitDraft, ApproveDraft and DiscardDraft: the wizard's targets step and Freigabe actions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from diffus.crossposting.application.drafts import ApproveDraft, DiscardDraft, SubmitDraft
from diffus.crossposting.application.publish_draft import PublishDraft
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    Destination,
    DraftImage,
    DraftStatus,
    PostDraft,
    PublishTargets,
)
from diffus.crossposting.domain.errors import DraftError
from tests.crossposting.fakes import (
    FakeChannels,
    FakeDrafts,
    FakePublisher,
    FakeSink,
    FakeUnitOfWork,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TELEGRAM = Destination("telegram", "chat1")
SIGNAL = Destination("signal", "chat2")


def make_draft(status: DraftStatus = DraftStatus.DRAFT) -> PostDraft:
    draft = PostDraft.new(caption="Hallo", images=[DraftImage("image/jpeg", 1, 1, b"x")], now=NOW)
    draft.status = status
    return draft


async def seed(
    draft: PostDraft | None,
    channels: FakeChannels | None = None,
    destinations: Sequence[Destination] = (TELEGRAM, SIGNAL),
) -> tuple[SubmitDraft, PublishDraft, FakeUnitOfWork]:
    uow = FakeUnitOfWork(
        drafts=FakeDrafts(), channels=channels if channels is not None else FakeChannels()
    )
    if draft is not None:
        await uow.drafts.add(draft)
        await uow.commit()
    publish = PublishDraft(
        uow=uow,
        publisher=FakePublisher(),
        sinks={"telegram": FakeSink(), "signal": FakeSink()},
        destinations=list(destinations),
        public_base_url="https://example.com",
    )
    submit = SubmitDraft(uow=uow, publish=publish, destinations=list(destinations))
    return submit, publish, uow


# -- SubmitDraft: immediate vs queued ------------------------------------------


async def test_all_chosen_channels_auto_publishes_immediately():
    draft = make_draft()
    submit, _publish, uow = await seed(draft, channels=FakeChannels({TELEGRAM: True}))

    result = await submit.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))

    assert result.queued is False
    assert result.post is not None
    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert stored.status == DraftStatus.PUBLISHED


async def test_a_non_auto_channel_queues_for_review_instead_of_publishing():
    draft = make_draft()
    submit, _publish, uow = await seed(draft, channels=FakeChannels({TELEGRAM: False}))

    result = await submit.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))

    assert result.queued is True
    assert result.post is None
    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert stored.status == DraftStatus.REVIEW
    assert stored.targets == PublishTargets(instagram=False, destinations=(TELEGRAM,))


async def test_instagram_chosen_with_its_switch_off_queues_despite_auto_telegram():
    draft = make_draft()
    submit, _publish, uow = await seed(
        draft, channels=FakeChannels({TELEGRAM: True, INSTAGRAM_CHANNEL: False})
    )

    result = await submit.run(draft.id, PublishTargets(instagram=True, destinations=(TELEGRAM,)))

    assert result.queued is True
    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert stored.status == DraftStatus.REVIEW


# -- SubmitDraft: refusals ------------------------------------------------------


async def test_submit_an_unknown_draft_is_refused():
    submit, _publish, _uow = await seed(None)

    with pytest.raises(DraftError, match="Entwurf nicht gefunden"):
        await submit.run("nope", PublishTargets(instagram=False, destinations=(TELEGRAM,)))


async def test_submit_a_non_draft_status_is_refused():
    draft = make_draft(status=DraftStatus.PUBLISHED)
    submit, _publish, _uow = await seed(draft)

    with pytest.raises(DraftError, match="schon veröffentlicht"):
        await submit.run(draft.id, PublishTargets(instagram=False, destinations=(TELEGRAM,)))


async def test_submit_with_no_target_at_all_is_refused():
    draft = make_draft()
    submit, _publish, _uow = await seed(draft)

    with pytest.raises(DraftError, match="Mindestens ein Ziel"):
        await submit.run(draft.id, PublishTargets(instagram=False, destinations=()))


async def test_submit_with_an_unconfigured_destination_is_refused():
    draft = make_draft()
    submit, _publish, _uow = await seed(draft)
    unconfigured = Destination("telegram", "not-configured")

    with pytest.raises(DraftError, match="Unbekanntes Ziel"):
        await submit.run(draft.id, PublishTargets(instagram=False, destinations=(unconfigured,)))


# -- ApproveDraft ---------------------------------------------------------------


async def test_approve_draft_publishes_with_the_given_targets():
    draft = make_draft(status=DraftStatus.REVIEW)
    draft.targets = PublishTargets(instagram=False, destinations=(TELEGRAM,))
    _submit, publish, uow = await seed(draft)
    approve = ApproveDraft(publish=publish)

    post = await approve.run(draft.id, PublishTargets(instagram=False, destinations=(SIGNAL,)))

    assert post is not None
    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert stored.status == DraftStatus.PUBLISHED
    assert stored.targets == PublishTargets(instagram=False, destinations=(SIGNAL,))


# -- DiscardDraft -----------------------------------------------------------------


@pytest.mark.parametrize("status", [DraftStatus.DRAFT, DraftStatus.REVIEW, DraftStatus.FAILED])
async def test_discard_deletes_an_unpublished_draft(status):
    draft = make_draft(status=status)
    uow = FakeUnitOfWork(drafts=FakeDrafts())
    await uow.drafts.add(draft)
    await uow.commit()
    discard = DiscardDraft(uow=uow)

    await discard.run(draft.id)

    assert await uow.drafts.get(draft.id) is None


async def test_discard_leaves_a_published_draft_alone():
    draft = make_draft(status=DraftStatus.PUBLISHED)
    uow = FakeUnitOfWork(drafts=FakeDrafts())
    await uow.drafts.add(draft)
    await uow.commit()
    discard = DiscardDraft(uow=uow)

    await discard.run(draft.id)

    assert await uow.drafts.get(draft.id) is not None


async def test_discard_of_an_unknown_draft_does_nothing():
    uow = FakeUnitOfWork(drafts=FakeDrafts())
    discard = DiscardDraft(uow=uow)

    await discard.run("nope")  # must not raise
