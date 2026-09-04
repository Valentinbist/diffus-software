"""CreateDraft: the upload half of the publishing wizard."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diffus.crossposting.application.drafts import CreateDraft
from diffus.crossposting.domain.entities import DraftStatus
from diffus.crossposting.domain.errors import DraftError, InvalidImageError, UploadTooLargeError
from tests.crossposting.fakes import FakeImageProcessor, FakeUnitOfWork

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_create(fail_images: bool = False) -> tuple[CreateDraft, FakeUnitOfWork]:
    uow = FakeUnitOfWork()
    return CreateDraft(uow=uow, images=FakeImageProcessor(fail=fail_images)), uow


async def test_happy_path_normalises_every_upload_and_commits_once():
    create, uow = make_create()
    uploads = [("a.jpg", b"one"), ("b.jpg", b"two")]

    draft = await create.run("Hallo", uploads, now=NOW)

    assert draft.status == DraftStatus.DRAFT
    assert draft.caption == "Hallo"
    assert [img.data for img in draft.images] == [b"one", b"two"]
    assert all(img.content_type == "image/jpeg" for img in draft.images)
    assert draft.created_at == NOW
    assert uow.commits == 1

    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert [img.data for img in stored.images] == [b"one", b"two"]


async def test_no_upload_is_refused():
    create, uow = make_create()

    with pytest.raises(InvalidImageError):
        await create.run("Hallo", [], now=NOW)

    assert uow.commits == 0


async def test_more_than_ten_uploads_is_refused():
    create, uow = make_create()
    uploads = [(f"{i}.jpg", b"x") for i in range(11)]

    with pytest.raises(UploadTooLargeError):
        await create.run("Hallo", uploads, now=NOW)

    assert uow.commits == 0


async def test_more_than_20mb_total_is_refused():
    create, uow = make_create()
    uploads = [("a.jpg", b"x" * (11 * 1024 * 1024)), ("b.jpg", b"x" * (10 * 1024 * 1024))]

    with pytest.raises(UploadTooLargeError):
        await create.run("Hallo", uploads, now=NOW)

    assert uow.commits == 0


async def test_a_too_long_caption_is_refused():
    create, uow = make_create()

    with pytest.raises(DraftError):
        await create.run("x" * 2201, [("a.jpg", b"one")], now=NOW)

    assert uow.commits == 0


async def test_a_failing_image_processor_propagates_the_error_and_writes_nothing():
    create, uow = make_create(fail_images=True)

    with pytest.raises(InvalidImageError):
        await create.run("Hallo", [("a.jpg", b"one")], now=NOW)

    assert uow.commits == 0


async def test_event_ref_is_stored_on_the_draft():
    create, uow = make_create()

    draft = await create.run(
        "Hallo", [("a.jpg", b"one")], now=NOW, event_ref="calendar:e1"
    )

    assert draft.event_ref == "calendar:e1"
    stored = await uow.drafts.get(draft.id)
    assert stored is not None
    assert stored.event_ref == "calendar:e1"


async def test_event_ref_defaults_to_none():
    create, _uow = make_create()

    draft = await create.run("Hallo", [("a.jpg", b"one")], now=NOW)

    assert draft.event_ref is None
