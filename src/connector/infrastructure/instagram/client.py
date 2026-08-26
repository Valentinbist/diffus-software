"""Instagram Graph API adapter: implements both PostSource and AuthGateway."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from connector.config import Settings
from connector.domain.entities import MediaItem, MediaType, Post, Token
from connector.domain.errors import NotConnectedError
from connector.domain.ports import TokenRepository

DEFAULT_EXPIRES_IN = 5_184_000  # 60 days, Instagram's documented default

MEDIA_FIELDS = (
    "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
    "children{media_type,media_url,thumbnail_url}"
)


class InstagramClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings, tokens: TokenRepository) -> None:
        self.http = http
        self.settings = settings
        self.tokens = tokens

    # -- AuthGateway ---------------------------------------------------

    def authorize_url(self) -> str:
        params = {
            "client_id": self.settings.ig_app_id,
            "redirect_uri": self.settings.ig_redirect_uri,
            "response_type": "code",
            "scope": "instagram_business_basic",
        }
        return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str) -> Token:
        resp = await self.http.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": self.settings.ig_app_id,
                "client_secret": self.settings.ig_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.ig_redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        entry = payload["data"][0] if "data" in payload else payload

        short_lived_token = entry["access_token"]
        raw_user_id = entry.get("user_id")
        ig_user_id = str(raw_user_id) if raw_user_id is not None else None

        exchange_resp = await self.http.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.settings.ig_app_secret,
                "access_token": short_lived_token,
            },
        )
        exchange_resp.raise_for_status()
        exchange_payload = exchange_resp.json()

        now = datetime.now(timezone.utc)
        expires_in = exchange_payload.get("expires_in", DEFAULT_EXPIRES_IN)
        return Token(
            access_token=exchange_payload["access_token"],
            ig_user_id=ig_user_id,
            expires_at=now + timedelta(seconds=expires_in),
            refreshed_at=now,
        )

    async def refresh(self, token: Token) -> Token:
        resp = await self.http.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token.access_token},
        )
        resp.raise_for_status()
        payload = resp.json()

        now = datetime.now(timezone.utc)
        expires_in = payload.get("expires_in", DEFAULT_EXPIRES_IN)
        return Token(
            access_token=payload["access_token"],
            ig_user_id=token.ig_user_id,
            expires_at=now + timedelta(seconds=expires_in),
            refreshed_at=now,
        )

    # -- PostSource ------------------------------------------------------

    async def fetch_recent(self, limit: int = 25) -> list[Post]:
        token = await self.tokens.get()
        if token is None:
            raise NotConnectedError("Instagram is not connected")

        resp = await self.http.get(
            "https://graph.instagram.com/me/media",
            params={
                "fields": MEDIA_FIELDS,
                "limit": limit,
                "access_token": token.access_token,
            },
        )
        resp.raise_for_status()
        return self._parse(resp.json())

    @staticmethod
    def _parse(payload: dict) -> list[Post]:
        posts: list[Post] = []
        for item in payload.get("data", []):
            if item.get("media_type") == "CAROUSEL_ALBUM":
                raw_children = item.get("children", {}).get("data", [])
            else:
                raw_children = [item]

            media_items: list[MediaItem] = []
            for child in raw_children:
                url = child.get("media_url")
                if url and child.get("media_type") == "VIDEO":
                    media_items.append(MediaItem(url=url, type=MediaType.VIDEO))
                    continue
                if not url:
                    url = child.get("thumbnail_url")
                if not url:
                    continue
                media_items.append(MediaItem(url=url, type=MediaType.IMAGE))

            if not media_items:
                continue

            posts.append(
                Post(
                    id=item["id"],
                    caption=item.get("caption"),
                    permalink=item.get("permalink", ""),
                    media=tuple(media_items),
                    posted_at=datetime.fromisoformat(item["timestamp"]),
                )
            )
        return posts
