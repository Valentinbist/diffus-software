"""Instagram Graph API adapter: implements PostSource, AuthGateway and MediaPublisher."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from diffus.crossposting.domain.entities import AccessToken, MediaItem, MediaType, Post, Token
from diffus.crossposting.domain.errors import PublishError

DEFAULT_EXPIRES_IN = 5_184_000  # 60 days, Instagram's documented default

MEDIA_FIELDS = (
    "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
    "children{media_type,media_url,thumbnail_url}"
)

# The graph.instagram.com host all publishing calls use, separate from the
# oauth/token hosts above.
GRAPH = "https://graph.instagram.com"

# instagram_business_basic reads; instagram_business_content_publish is what
# lets Token.can_publish be true. Changing this string forces every already
# connected account through a one-time re-connect, which is exactly what a
# newly required scope needs.
SCOPES = "instagram_business_basic,instagram_business_content_publish"

# How long to wait for a media container to finish processing before giving up.
READINESS_POLL_ATTEMPTS = 10
READINESS_POLL_INTERVAL_SECONDS = 2.0


class InstagramClient:
    source = "instagram"
    # Class-level alias so callers/tests can reach the scope string as
    # InstagramClient.SCOPES without importing the module constant separately.
    SCOPES = SCOPES

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.http = http
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        # Injectable so tests can poll the readiness loop without really sleeping.
        self.sleep = sleep

    # -- AuthGateway ---------------------------------------------------

    def authorize_url(self) -> str:
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.SCOPES,
        }
        return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str) -> Token:
        resp = await self.http.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        entry = payload["data"][0] if "data" in payload else payload

        short_lived_token = entry["access_token"]
        raw_user_id = entry.get("user_id")
        external_user_id = str(raw_user_id) if raw_user_id is not None else None

        exchange_resp = await self.http.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.app_secret,
                "access_token": short_lived_token,
            },
        )
        exchange_resp.raise_for_status()
        exchange_payload = exchange_resp.json()

        now = datetime.now(UTC)
        expires_in = exchange_payload.get("expires_in", DEFAULT_EXPIRES_IN)
        return Token(
            source=self.source,
            access_token=AccessToken(exchange_payload["access_token"]),
            external_user_id=external_user_id,
            expires_at=now + timedelta(seconds=expires_in),
            refreshed_at=now,
            scopes=self.SCOPES,
        )

    async def refresh(self, token: Token) -> Token:
        resp = await self.http.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token.access_token.value,
            },
        )
        resp.raise_for_status()
        payload = resp.json()

        now = datetime.now(UTC)
        expires_in = payload.get("expires_in", DEFAULT_EXPIRES_IN)
        return Token(
            source=self.source,
            access_token=AccessToken(payload["access_token"]),
            external_user_id=token.external_user_id,
            expires_at=now + timedelta(seconds=expires_in),
            refreshed_at=now,
            scopes=token.scopes,
        )

    # -- PostSource ------------------------------------------------------

    async def fetch_recent(self, token: Token, limit: int = 25) -> list[Post]:
        resp = await self.http.get(
            "https://graph.instagram.com/me/media",
            params={
                "fields": MEDIA_FIELDS,
                "limit": limit,
                "access_token": token.access_token.value,
            },
        )
        resp.raise_for_status()
        return self._parse(resp.json())

    @classmethod
    def _parse(cls, payload: dict) -> list[Post]:
        posts: list[Post] = []
        for item in payload.get("data", []):
            if item.get("media_type") == "CAROUSEL_ALBUM":
                raw_children = item.get("children", {}).get("data", [])
            else:
                raw_children = [item]

            media_items: list[MediaItem] = []
            for child in raw_children:
                url = child.get("media_url")
                thumbnail = child.get("thumbnail_url")
                if url and child.get("media_type") == "VIDEO":
                    media_items.append(
                        MediaItem(url=url, type=MediaType.VIDEO, thumbnail_url=thumbnail)
                    )
                    continue
                if not url:
                    url = thumbnail
                if not url:
                    continue
                media_items.append(MediaItem(url=url, type=MediaType.IMAGE))

            if not media_items:
                continue

            posts.append(
                Post(
                    id=item["id"],
                    source=cls.source,
                    caption=item.get("caption"),
                    permalink=item.get("permalink", ""),
                    media=tuple(media_items),
                    posted_at=datetime.fromisoformat(item["timestamp"]),
                )
            )
        return posts

    # -- MediaPublisher ----------------------------------------------------
    #
    # Single image: one container carries `image_url` + `caption` directly.
    # Carousel: each image becomes its own `is_carousel_item` container first
    # (children, in order), then one more container of media_type=CAROUSEL
    # ties them together with the caption. Either way, the resulting
    # container is polled until Meta finishes processing it before
    # media_publish turns it into an actual post.

    async def publish_images(self, token: Token, image_urls: Sequence[str], caption: str) -> str:
        user = token.external_user_id or "me"
        access_token = token.access_token.value

        if len(image_urls) == 1:
            container = await self._media(
                user, {"image_url": image_urls[0], "caption": caption, "access_token": access_token}
            )
        else:
            child_ids = [
                (
                    await self._media(
                        user,
                        {
                            "image_url": url,
                            "is_carousel_item": "true",
                            "access_token": access_token,
                        },
                    )
                )["id"]
                for url in image_urls
            ]
            container = await self._media(
                user,
                {
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "caption": caption,
                    "access_token": access_token,
                },
            )

        container_id = container["id"]
        await self._wait_until_ready(container_id, access_token)

        published = await self._request(
            "post",
            f"{user}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        return published["id"]

    async def _media(self, user: str, data: dict[str, str]) -> dict:
        return await self._request("post", f"{user}/media", data=data)

    async def _wait_until_ready(self, container_id: str, access_token: str) -> None:
        for _ in range(READINESS_POLL_ATTEMPTS):
            payload = await self._request(
                "get",
                container_id,
                params={"fields": "status_code", "access_token": access_token},
            )
            status = payload.get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise PublishError(f"Instagram: Verarbeitung fehlgeschlagen ({status}).")
            await self.sleep(READINESS_POLL_INTERVAL_SECONDS)
        raise PublishError("Instagram: Zeitüberschreitung bei der Verarbeitung des Bildes.")

    async def fetch_post(self, token: Token, post_id: str) -> Post:
        payload = await self._request(
            "get",
            post_id,
            params={"fields": MEDIA_FIELDS, "access_token": token.access_token.value},
        )
        posts = self._parse({"data": [payload]})
        if not posts:
            raise PublishError(
                "Instagram: Der veröffentlichte Post konnte nicht gelesen werden."
            )
        return posts[0]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        """POST/GET under GRAPH, mapping a non-2xx response to a PublishError.

        Built from the JSON error body, never from the request itself, so an
        error message never carries the access token that a query string or
        form body holds.
        """
        resp = await self.http.request(method, f"{GRAPH}/{path}", data=data, params=params)
        if resp.is_success:
            return resp.json()
        message = str(resp.status_code)
        with contextlib.suppress(Exception):  # malformed error body still needs a message
            message = resp.json()["error"]["message"]
        raise PublishError(f"Instagram: {message}")
