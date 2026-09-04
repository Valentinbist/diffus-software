"""FallbackMediaGateway: CDN first, stored previews when the CDN link has gone stale."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diffus.crossposting.domain.entities import MediaItem, MediaType, Post, Preview
from diffus.crossposting.domain.errors import DeliveryError
from diffus.crossposting.infrastructure.media.fallback import FallbackMediaGateway
from tests.crossposting.fakes import FakeMedia, FakeUnitOfWork


def make_post(media: tuple[MediaItem, ...]) -> Post:
    return Post(
        id="p1",
        source="instagram",
        caption="x",
        permalink="https://instagram.com/p/p1/",
        media=media,
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_the_cdn_result_is_used_as_is_when_it_works():
    post = make_post((MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),))
    gateway = FallbackMediaGateway(cdn=FakeMedia(), uow=FakeUnitOfWork())

    async with gateway.fetch(post) as files:
        # FakeMedia.fetch always yields an empty list; a real empty result is
        # not a failure, so the fallback (which would need a stored preview
        # that doesn't exist here) must never be triggered.
        assert files == []


async def test_falls_back_to_a_stored_preview_when_the_cdn_fetch_fails():
    post = make_post((MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),))
    uow = FakeUnitOfWork()
    await uow.previews.save(
        Preview(post_id="p1", index=0, content_type="image/jpeg", data=b"stored-still")
    )
    await uow.commit()
    gateway = FallbackMediaGateway(cdn=FakeMedia(fail_fetch=True), uow=uow)

    async with gateway.fetch(post) as files:
        assert len(files) == 1
        assert files[0].item.type == MediaType.IMAGE
        assert files[0].path.read_bytes() == b"stored-still"


async def test_a_video_falls_back_to_its_stored_still_frame_as_an_image():
    post = make_post((MediaItem(url="https://cdn.example.com/1.mp4", type=MediaType.VIDEO),))
    uow = FakeUnitOfWork()
    await uow.previews.save(
        Preview(post_id="p1", index=0, content_type="image/jpeg", data=b"still-frame")
    )
    await uow.commit()
    gateway = FallbackMediaGateway(cdn=FakeMedia(fail_fetch=True), uow=uow)

    async with gateway.fetch(post) as files:
        # The stored preview is a JPEG still, never the original clip.
        assert files[0].item.type == MediaType.IMAGE
        assert files[0].path.read_bytes() == b"still-frame"


async def test_a_missing_preview_raises_delivery_error():
    post = make_post((MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),))
    uow = FakeUnitOfWork()  # no stored preview at all
    gateway = FallbackMediaGateway(cdn=FakeMedia(fail_fetch=True), uow=uow)

    with pytest.raises(DeliveryError, match="nicht mehr verfügbar"):
        async with gateway.fetch(post):
            pass  # pragma: no cover - never reached


async def test_one_missing_index_among_several_still_raises():
    post = make_post(
        (
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
            MediaItem(url="https://cdn.example.com/2.jpg", type=MediaType.IMAGE),
        )
    )
    uow = FakeUnitOfWork()
    await uow.previews.save(Preview(post_id="p1", index=0, content_type="image/jpeg", data=b"one"))
    await uow.commit()  # index 1 has no stored preview
    gateway = FallbackMediaGateway(cdn=FakeMedia(fail_fetch=True), uow=uow)

    with pytest.raises(DeliveryError):
        async with gateway.fetch(post):
            pass  # pragma: no cover - never reached


async def test_download_image_always_delegates_to_the_cdn():
    cdn = FakeMedia(images={"https://cdn.example.com/x.jpg": b"data"})
    gateway = FallbackMediaGateway(cdn=cdn, uow=FakeUnitOfWork())

    result = await gateway.download_image("https://cdn.example.com/x.jpg")

    assert result == ("image/jpeg", b"data")
    assert cdn.downloads == ["https://cdn.example.com/x.jpg"]
