from __future__ import annotations

from datetime import UTC, datetime

from diffus.crossposting.application.draft_media import DraftMediaGateway
from diffus.crossposting.domain.entities import (
    DraftImage,
    MediaItem,
    MediaType,
    Post,
    PostDraft,
)


def make_draft() -> PostDraft:
    return PostDraft.new(
        caption="hi",
        images=[
            DraftImage("image/jpeg", 10, 10, b"one"),
            DraftImage("image/jpeg", 20, 20, b"two"),
        ],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_post(post_id: str, media_count: int) -> Post:
    return Post(
        id=post_id,
        source="diffus",
        caption="hi",
        permalink="",
        media=tuple(
            MediaItem(url=f"https://example.com/{i}", type=MediaType.IMAGE)
            for i in range(media_count)
        ),
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_fetch_writes_each_draft_image_to_its_own_temp_file():
    draft = make_draft()
    gateway = DraftMediaGateway(draft=draft)
    post = make_post("diffus:x", 2)

    async with gateway.fetch(post) as files:
        assert len(files) == 2
        assert files[0].path.name == "diffus:x-0.jpg"
        assert files[0].path.read_bytes() == b"one"
        assert files[1].path.read_bytes() == b"two"
        assert files[0].item is post.media[0]
        assert files[1].item is post.media[1]
        written_paths = [f.path for f in files]

    for path in written_paths:
        assert not path.exists()  # cleaned up once the context manager exits


async def test_download_image_always_returns_none():
    gateway = DraftMediaGateway(draft=make_draft())

    assert await gateway.download_image("https://example.com/x.jpg") is None
