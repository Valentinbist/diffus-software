"""TelegramSink.deliver against a mocked transport: no network, no bot token leaked."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from diffus.crossposting.domain.entities import MediaFile, MediaItem, MediaType, Post
from diffus.crossposting.infrastructure.telegram.sink import TelegramSink

BOT_TOKEN = "123456:ABC-token"


def make_post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def sink(requests: list[httpx.Request]) -> TelegramSink:
    def handler(request: httpx.Request) -> httpx.Response:
        request.read()  # materialize the multipart body so .content is available
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TelegramSink(http, BOT_TOKEN)


async def test_single_image_post_sends_one_photo(
    sink: TelegramSink, requests: list[httpx.Request], tmp_path: Path
):
    path = tmp_path / "p1-0.jpg"
    path.write_bytes(b"\xff\xd8jpeg")
    item = MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE)
    media = [MediaFile(item=item, path=path)]

    await sink.deliver(make_post(), "c1", media)

    assert len(requests) == 1
    request = requests[0]
    assert f"/bot{BOT_TOKEN}/sendPhoto" in str(request.url)
    body = request.content
    assert b'name="chat_id"' in body
    assert b"c1" in body
    assert b'name="photo"' in body
    assert b"\xff\xd8jpeg" in body


async def test_two_item_post_sends_one_media_group(
    sink: TelegramSink, requests: list[httpx.Request], tmp_path: Path
):
    path1 = tmp_path / "p1-0.jpg"
    path1.write_bytes(b"one")
    path2 = tmp_path / "p1-1.jpg"
    path2.write_bytes(b"two")
    item1 = MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE)
    item2 = MediaItem(url="https://cdn.example.com/2.jpg", type=MediaType.IMAGE)
    media = [MediaFile(item=item1, path=path1), MediaFile(item=item2, path=path2)]

    await sink.deliver(make_post(), "c1", media)

    assert len(requests) == 1
    request = requests[0]
    assert f"/bot{BOT_TOKEN}/sendMediaGroup" in str(request.url)
    body = request.content
    assert b'name="chat_id"' in body
    assert b"c1" in body
    assert b'name="m0"' in body
    assert b'name="m1"' in body
