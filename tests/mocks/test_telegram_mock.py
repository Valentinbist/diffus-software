"""Runs the real TelegramSink against mocks/telegram.py, over ASGITransport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from diffus.crossposting.domain.entities import MediaFile, MediaItem, MediaType, Post
from diffus.crossposting.domain.errors import DeliveryError
from diffus.crossposting.infrastructure.telegram.sink import TelegramSink
from mocks.telegram import State, create_app

BOT_TOKEN = "mock-bot-token"


@pytest.fixture
def state() -> State:
    s = State(bot_token=BOT_TOKEN)
    s.seed()
    return s


@pytest.fixture
async def http(state: State):
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as client:
        yield client


def make_sink(http: httpx.AsyncClient, bot_token: str = BOT_TOKEN) -> TelegramSink:
    return TelegramSink(http, bot_token, api_base="http://mock/telegram")


def make_post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        source="instagram",
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def make_media(tmp_path: Path, n: int) -> list[MediaFile]:
    files = []
    for i in range(n):
        path = tmp_path / f"{i}.jpg"
        path.write_bytes(f"img{i}".encode())
        files.append(MediaFile(item=MediaItem(url="u", type=MediaType.IMAGE), path=path))
    return files


# -- one image -> sendPhoto ---------------------------------------------------


async def test_one_image_sends_a_photo_recorded_with_caption_and_parse_mode(
    http: httpx.AsyncClient, tmp_path: Path
):
    sink = make_sink(http)

    await sink.deliver(make_post(), "c1", make_media(tmp_path, 1))

    resp = await http.get("/telegram/_calls")
    calls = resp.json()
    assert len(calls) == 1
    assert calls[0]["method"] == "sendPhoto"
    assert calls[0]["chat_id"] == "c1"
    assert calls[0]["parse_mode"] == "HTML"
    assert "caption" in calls[0]["caption"]


# -- three images -> sendMediaGroup -------------------------------------------


async def test_three_images_send_one_media_group_with_a_three_item_media_field(
    http: httpx.AsyncClient, tmp_path: Path
):
    sink = make_sink(http)

    await sink.deliver(make_post(), "c1", make_media(tmp_path, 3))

    resp = await http.get("/telegram/_calls")
    calls = resp.json()
    assert len(calls) == 1
    assert calls[0]["method"] == "sendMediaGroup"
    media = json.loads(calls[0]["media"])
    assert len(media) == 3


# -- wrong token ----------------------------------------------------------------


async def test_a_wrong_bot_token_raises_delivery_error(http: httpx.AsyncClient, tmp_path: Path):
    sink = make_sink(http, bot_token="not-the-real-token")

    with pytest.raises(DeliveryError):
        await sink.deliver(make_post(), "c1", make_media(tmp_path, 1))


# -- rate-limit knob: the sink retries and succeeds ---------------------------


async def test_rate_limit_knob_makes_the_sink_retry_and_then_succeed(
    http: httpx.AsyncClient, tmp_path: Path, state: State
):
    # "every 3rd call" — pre-seed the counter so the very next attempt lands
    # on the 3rd (429), and its retry lands on the 4th (succeeds), rather
    # than depending on how many prior calls this test happened to make.
    state.rate_limit_every = 3
    state.attempt_counter = 2
    sink = make_sink(http)

    await sink.deliver(make_post(), "c1", make_media(tmp_path, 1))

    resp = await http.get("/telegram/_calls")
    calls = resp.json()
    # Both attempts are recorded: the rate-limited one and the retry that
    # succeeded — /telegram/_calls shows the whole sequence, not just what
    # eventually went out.
    assert len(calls) == 2
    assert calls[0]["status_code"] == 429
    assert calls[1]["status_code"] == 200
    assert state.attempt_counter == 4
