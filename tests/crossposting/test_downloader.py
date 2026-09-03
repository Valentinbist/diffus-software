"""HttpMediaGateway.download_image against a mocked transport: no network."""

from __future__ import annotations

import httpx
import pytest

from diffus.crossposting.infrastructure.media import downloader
from diffus.crossposting.infrastructure.media.downloader import HttpMediaGateway


def handler(request: httpx.Request) -> httpx.Response:
    match request.url.path:
        case "/still.jpg":
            return httpx.Response(
                200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg; charset=binary"}
            )
        case "/page":
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        case "/big.png":
            return httpx.Response(200, content=b"x" * 64, headers={"content-type": "image/png"})
        case _:
            return httpx.Response(404)


@pytest.fixture
def gateway():
    return HttpMediaGateway(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_download_image_returns_bare_content_type_and_bytes(gateway):
    assert await gateway.download_image("https://cdn.example.com/still.jpg") == (
        "image/jpeg",
        b"\xff\xd8jpeg",
    )


async def test_download_image_ignores_things_that_are_not_images(gateway):
    assert await gateway.download_image("https://cdn.example.com/page") is None


async def test_download_image_gives_up_on_oversized_bodies(gateway, monkeypatch):
    monkeypatch.setattr(downloader, "MAX_IMAGE_BYTES", 32)

    assert await gateway.download_image("https://cdn.example.com/big.png") is None


async def test_download_image_raises_on_http_errors_so_the_caller_can_log_them(gateway):
    with pytest.raises(httpx.HTTPStatusError):
        await gateway.download_image("https://cdn.example.com/missing.jpg")
