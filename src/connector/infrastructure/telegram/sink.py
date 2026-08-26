"""Telegram Bot API adapter: implements PostSink."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

import httpx

from connector.domain.entities import MediaType, Post
from connector.domain.errors import DeliveryError
from connector.infrastructure.telegram.render import render_caption

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MEDIA_GROUP_ITEMS = 10
REQUEST_TIMEOUT = 120.0
MAX_RETRIES = 3
MAX_ERROR_BODY_LENGTH = 500

FilesFactory = Callable[[], dict[str, tuple[str, IO[bytes]]]]


class TelegramSink:
    def __init__(self, http: httpx.AsyncClient, bot_token: str) -> None:
        self.http = http
        self.bot_token = bot_token

    async def deliver(self, post: Post, chat_id: str, media_paths: Sequence[Path]) -> None:
        if not media_paths:
            raise DeliveryError("no media to deliver")

        caption = render_caption(post)
        items = list(zip(post.media, media_paths, strict=True))

        if len(items) == 1:
            media_item, path = items[0]
            is_video = media_item.type == MediaType.VIDEO
            method = "sendVideo" if is_video else "sendPhoto"
            field = "video" if is_video else "photo"

            def make_files(path: Path = path, field: str = field) -> dict:
                return {field: (path.name, path.open("rb"))}

            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            await self._call(method, data=data, make_files=make_files)
            return

        items = items[:MAX_MEDIA_GROUP_ITEMS]
        media_descriptor = []
        for i, (media_item, _path) in enumerate(items):
            entry: dict[str, str] = {
                "type": "video" if media_item.type == MediaType.VIDEO else "photo",
                "media": f"attach://m{i}",
            }
            if i == 0:
                entry["caption"] = caption
                entry["parse_mode"] = "HTML"
            media_descriptor.append(entry)

        def make_files(items: list = items) -> dict:
            return {
                f"m{i}": (path.name, path.open("rb"))
                for i, (_media_item, path) in enumerate(items)
            }

        data = {"chat_id": chat_id, "media": json.dumps(media_descriptor)}
        await self._call("sendMediaGroup", data=data, make_files=make_files)

    async def _call(self, method: str, data: dict, make_files: FilesFactory) -> None:
        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/{method}"

        for attempt in range(1, MAX_RETRIES + 1):
            files = make_files()
            try:
                resp = await self.http.post(
                    url, data=data, files=files, timeout=REQUEST_TIMEOUT
                )
            finally:
                for _field, (_filename, fh) in files.items():
                    fh.close()

            if resp.status_code == 429:
                retry_after = 1
                # Fall back to the default backoff if the 429 body isn't parseable.
                with contextlib.suppress(Exception):
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 1)
                logger.warning(
                    "telegram rate limited on %s (attempt %s/%s), sleeping %ss",
                    method,
                    attempt,
                    MAX_RETRIES,
                    retry_after + 1,
                )
                await asyncio.sleep(retry_after + 1)
                continue

            if resp.status_code >= 400:
                body = resp.text[:MAX_ERROR_BODY_LENGTH]
                raise DeliveryError(f"telegram {method} failed ({resp.status_code}): {body}")

            return

        raise DeliveryError(f"telegram {method} failed after {MAX_RETRIES} attempts (rate limited)")
