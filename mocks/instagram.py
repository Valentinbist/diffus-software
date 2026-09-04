"""Mock of Instagram's OAuth + Graph API, the surface `InstagramClient` calls.

Stands in for three real hosts, each behind its own prefix here:

- `https://www.instagram.com/oauth/authorize`  -> `GET /www/oauth/authorize`
- `https://api.instagram.com/oauth/access_token` -> `POST /api/oauth/access_token`
- `https://graph.instagram.com/...`  -> `/graph/...`:
  - `GET /graph/access_token` (`ig_exchange_token`) and
    `GET /graph/refresh_access_token` (`ig_refresh_token`)
  - `GET /graph/me/media` (`fetch_recent`)
  - `POST /graph/{user}/media` (create a media container; the mock fetches
    `image_url` itself, exactly like real Instagram does)
  - `GET /graph/{container}?fields=status_code` (readiness poll)
  - `POST /graph/{user}/media_publish` (turn a finished container into a post)
  - `GET /graph/{media_id}?fields=...` (`fetch_post`)
  - `GET /graph/{user}/content_publishing_limit` (the 100/24h quota)
  - `GET /graph/mock-media/{name}` — not a real Instagram endpoint; where the
    placeholder JPEGs/video blobs this module hands out as `media_url` /
    `thumbnail_url` actually live.

In-memory only, reset by `State.seed()`. No auth beyond what the real API
enforces: an `access_token` the mock itself issued, checked on every
`/graph/*` call, mapping an unknown one to the same
`{"error": {"message": "Invalid OAuth access token", "code": 190}}` shape
Meta returns.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from mocks.dates import german_date, siebdruck_day
from mocks.media import placeholder_jpeg, placeholder_video_bytes

DEFAULT_QUOTA = 100
QUOTA_ENV = "MOCK_INSTAGRAM_QUOTA"

# (content type, bytes) for a URL, or raises. The real implementation (a
# plain httpx GET) is what production/Docker uses — the mock's own outbound
# fetch of a draft's `image_url` is a genuine network call across the compose
# network. Contract tests running the whole thing in-process over
# httpx.ASGITransport have no real socket to hit, so they replace this with
# one that fetches through the very same ASGI app instead.
FetchFn = Callable[[str], Awaitable[tuple[str, bytes]]]


async def _http_fetch(url: str) -> tuple[str, bytes]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        return content_type, resp.content


@dataclass
class MediaChild:
    media_type: str  # IMAGE or VIDEO
    name: str  # key into State.media_store
    thumbnail_name: str | None = None


@dataclass
class MediaPost:
    id: str
    caption: str | None
    media_type: str  # IMAGE, VIDEO, CAROUSEL_ALBUM
    timestamp: str  # ISO, "+0000" suffix like real Instagram
    permalink: str
    name: str | None = None  # single IMAGE/VIDEO: key into State.media_store
    thumbnail_name: str | None = None
    children: list[MediaChild] = field(default_factory=list)


@dataclass
class Container:
    id: str
    kind: str  # "single" | "carousel_item" | "carousel"
    caption: str = ""
    child_ids: list[str] = field(default_factory=list)
    name: str | None = None  # stored placeholder key, once fetched
    error: str | None = None
    polled: int = 0

    @property
    def status(self) -> str:
        return "ERROR" if self.error else "OK"


@dataclass
class State:
    quota_limit: int = DEFAULT_QUOTA
    fetch: FetchFn = field(default=_http_fetch)

    user_id: int = 17841400000000001
    codes: set[str] = field(default_factory=set)
    code_counter: int = 0
    last_scope: str = ""
    short_tokens: set[str] = field(default_factory=set)
    short_token_counter: int = 0
    long_tokens: set[str] = field(default_factory=set)
    long_token_counter: int = 0

    media: list[MediaPost] = field(default_factory=list)  # newest first
    containers: dict[str, Container] = field(default_factory=dict)
    container_counter: int = 0
    media_counter: int = 0
    media_store: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # name -> (ct, bytes)
    quota_usage: int = 0

    def all_tokens(self) -> set[str]:
        return self.short_tokens | self.long_tokens

    def store_media_bytes(self, name: str, content_type: str, data: bytes) -> None:
        self.media_store[name] = (content_type, data)

    def seed(self) -> None:
        self.codes.clear()
        self.code_counter = 0
        self.last_scope = ""
        self.short_tokens.clear()
        self.short_token_counter = 0
        self.long_tokens.clear()
        self.long_token_counter = 0
        self.media.clear()
        self.containers.clear()
        self.container_counter = 0
        self.media_counter = 0
        self.media_store.clear()
        self.quota_usage = 0

        now = datetime.now(UTC)

        def ts(days_ago: int) -> str:
            return (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")

        self.store_media_bytes("seed-1.jpg", "image/jpeg", placeholder_jpeg("seed-1"))
        self.media.append(
            MediaPost(
                id="seed-1",
                caption="Neuer Siebdruck-Kurs startet nächste Woche! 🎨",
                media_type="IMAGE",
                timestamp=ts(1),
                permalink="https://www.instagram.com/p/mock-seed-1/",
                name="seed-1.jpg",
            )
        )

        children = []
        for i in range(1, 4):
            name = f"seed-2-{i}.jpg"
            self.store_media_bytes(name, "image/jpeg", placeholder_jpeg(f"seed-2-{i}"))
            children.append(MediaChild(media_type="IMAGE", name=name))
        self.media.append(
            MediaPost(
                id="seed-2",
                caption="Rückblick: Plenum letztes Wochenende",
                media_type="CAROUSEL_ALBUM",
                timestamp=ts(3),
                permalink="https://www.instagram.com/p/mock-seed-2/",
                children=children,
            )
        )

        self.store_media_bytes("seed-3.mp4", "video/mp4", placeholder_video_bytes("seed-3"))
        self.store_media_bytes("seed-3-thumb.jpg", "image/jpeg", placeholder_jpeg("seed-3"))
        self.media.append(
            MediaPost(
                id="seed-3",
                caption="Video vom letzten Konzert im Haupt-Raum",
                media_type="VIDEO",
                timestamp=ts(6),
                permalink="https://www.instagram.com/p/mock-seed-3/",
                name="seed-3.mp4",
                thumbnail_name="seed-3-thumb.jpg",
            )
        )

        self.store_media_bytes("seed-4.jpg", "image/jpeg", placeholder_jpeg("seed-4"))
        # Names the same date the kalender mock seeds its Siebdruck event on.
        siebdruck = german_date(siebdruck_day(datetime.now(UTC).date()))
        self.media.append(
            MediaPost(
                id="seed-4",
                caption=f"Save the date: 📅 {siebdruck}, Siebdruck-Nachmittag",
                media_type="IMAGE",
                timestamp=ts(10),
                permalink="https://www.instagram.com/p/mock-seed-4/",
                name="seed-4.jpg",
            )
        )

    def find_media(self, media_id: str) -> MediaPost | None:
        return next((m for m in self.media if m.id == media_id), None)

    def as_state_dict(self) -> dict:
        return {
            "last_requested_scope": self.last_scope,
            "issued_codes": self.code_counter,
            "short_tokens": len(self.short_tokens),
            "long_tokens": len(self.long_tokens),
            "quota_usage": self.quota_usage,
            "quota_limit": self.quota_limit,
            "posts": [m.id for m in self.media],
            "containers": {
                cid: {"kind": c.kind, "status": c.status, "error": c.error}
                for cid, c in self.containers.items()
            },
        }


def _token_error() -> JSONResponse:
    return JSONResponse(
        {"error": {"message": "Invalid OAuth access token", "code": 190}}, status_code=400
    )


def _serialize(post: MediaPost, media_base: str) -> dict:
    def media_url(name: str) -> str:
        return f"{media_base}/mock-media/{name}"

    payload: dict = {
        "id": post.id,
        "caption": post.caption,
        "media_type": post.media_type,
        "permalink": post.permalink,
        "timestamp": post.timestamp,
    }
    if post.media_type == "CAROUSEL_ALBUM":
        payload["children"] = {
            "data": [
                {
                    "media_type": child.media_type,
                    "media_url": media_url(child.name),
                    **(
                        {"thumbnail_url": media_url(child.thumbnail_name)}
                        if child.thumbnail_name
                        else {}
                    ),
                }
                for child in post.children
            ]
        }
    else:
        if post.name:
            payload["media_url"] = media_url(post.name)
        if post.thumbnail_name:
            payload["thumbnail_url"] = media_url(post.thumbnail_name)
    return payload


def build_router(state: State | None = None) -> tuple[APIRouter, State]:
    if state is None:
        state = State(quota_limit=int(os.environ.get(QUOTA_ENV, str(DEFAULT_QUOTA))))
        state.seed()

    router = APIRouter()
    www_router = APIRouter(prefix="/www")
    api_router = APIRouter(prefix="/api")
    graph_router = APIRouter(prefix="/graph")

    # -- www.instagram.com: the browser-facing OAuth authorize step ---------

    @www_router.get("/oauth/authorize")
    async def authorize(
        client_id: str, redirect_uri: str, response_type: str = "code", scope: str = ""
    ):
        state.last_scope = scope
        state.code_counter += 1
        code = f"mock-code-{state.code_counter}"
        state.codes.add(code)
        return RedirectResponse(url=f"{redirect_uri}?code={code}", status_code=302)

    # -- api.instagram.com: short-lived token from the OAuth code -----------

    @api_router.post("/oauth/access_token")
    async def exchange_code(request: Request):
        form = await request.form()
        code = str(form.get("code", ""))
        if code not in state.codes:
            return JSONResponse({"error": {"message": "Invalid code"}}, status_code=400)
        state.codes.discard(code)  # one-time use, like the real endpoint
        state.short_token_counter += 1
        token = f"short-{state.short_token_counter}"
        state.short_tokens.add(token)
        return {"data": [{"access_token": token, "user_id": state.user_id}]}

    # -- graph.instagram.com --------------------------------------------
    # Literal routes first, the single-segment catch-all (container status /
    # fetch_post) last — Starlette matches in registration order, and that
    # catch-all would otherwise swallow /access_token, /refresh_access_token.

    @graph_router.get("/access_token")
    async def exchange_token(grant_type: str, client_secret: str, access_token: str):
        if access_token not in state.short_tokens:
            return _token_error()
        state.long_token_counter += 1
        token = f"long-{state.long_token_counter}"
        state.long_tokens.add(token)
        return {"access_token": token, "token_type": "bearer", "expires_in": 5_184_000}

    @graph_router.get("/refresh_access_token")
    async def refresh_token(grant_type: str, access_token: str):
        if access_token not in state.long_tokens:
            return _token_error()
        state.long_token_counter += 1
        token = f"long-{state.long_token_counter}"
        state.long_tokens.add(token)
        return {"access_token": token, "token_type": "bearer", "expires_in": 5_184_000}

    @graph_router.get("/me/media")
    async def me_media(request: Request, access_token: str, fields: str = "", limit: int = 25):
        if access_token not in state.all_tokens():
            return _token_error()
        media_base = str(request.base_url).rstrip("/") + "/graph"
        items = [_serialize(post, media_base) for post in state.media[:limit]]
        return {"data": items, "paging": {}}

    @graph_router.get("/mock-media/{name}")
    async def mock_media(name: str):
        stored = state.media_store.get(name)
        if stored is None:
            return JSONResponse({"error": "no such media"}, status_code=404)
        content_type, data = stored
        return Response(content=data, media_type=content_type)

    @graph_router.post("/{user}/media")
    async def create_media(user: str, request: Request):
        form = await request.form()
        access_token = str(form.get("access_token", ""))
        if access_token not in state.all_tokens():
            return _token_error()

        state.container_counter += 1
        container_id = f"c{state.container_counter}"

        if form.get("media_type") == "CAROUSEL":
            children = str(form.get("children", "")).split(",")
            state.containers[container_id] = Container(
                id=container_id,
                kind="carousel",
                caption=str(form.get("caption", "")),
                child_ids=[c for c in children if c],
            )
            return {"id": container_id}

        kind = "carousel_item" if form.get("is_carousel_item") == "true" else "single"
        container = Container(id=container_id, kind=kind, caption=str(form.get("caption", "")))
        state.containers[container_id] = container

        image_url = str(form.get("image_url", ""))
        try:
            content_type, data = await state.fetch(image_url)
        except Exception as exc:  # noqa: BLE001 - any fetch failure maps to a container error
            container.error = f"failed to fetch image_url: {exc}"
            return {"id": container_id}
        if not content_type.startswith("image/jpeg") and not content_type.startswith("image/jpg"):
            container.error = f"image_url did not serve a JPEG (got {content_type or 'unknown'})"
            return {"id": container_id}

        name = f"published-{container_id}.jpg"
        state.store_media_bytes(name, content_type, data)
        container.name = name
        return {"id": container_id}

    @graph_router.post("/{user}/media_publish")
    async def media_publish(user: str, request: Request):
        form = await request.form()
        access_token = str(form.get("access_token", ""))
        if access_token not in state.all_tokens():
            return _token_error()

        creation_id = str(form.get("creation_id", ""))
        container = state.containers.get(creation_id)
        if container is None or container.status == "ERROR":
            return JSONResponse(
                {"error": {"message": "Invalid parameter", "type": "OAuthException", "code": 100}},
                status_code=400,
            )
        if state.quota_usage >= state.quota_limit:
            return JSONResponse(
                {
                    "error": {
                        "message": "Application request limit reached",
                        "type": "OAuthException",
                        "code": 4,
                    }
                },
                status_code=400,
            )

        state.media_counter += 1
        media_id = str(state.user_id + state.media_counter)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")
        permalink = f"https://www.instagram.com/p/mock-{media_id}/"

        if container.kind == "carousel":
            children = []
            for child_id in container.child_ids:
                child = state.containers.get(child_id)
                if child is None or child.name is None:
                    continue
                children.append(MediaChild(media_type="IMAGE", name=child.name))
            post = MediaPost(
                id=media_id,
                caption=container.caption,
                media_type="CAROUSEL_ALBUM",
                timestamp=now,
                permalink=permalink,
                children=children,
            )
        else:
            post = MediaPost(
                id=media_id,
                caption=container.caption,
                media_type="IMAGE",
                timestamp=now,
                permalink=permalink,
                name=container.name,
            )
        state.media.insert(0, post)
        state.quota_usage += 1
        return {"id": media_id}

    @graph_router.get("/{user}/content_publishing_limit")
    async def content_publishing_limit(user: str, access_token: str):
        if access_token not in state.all_tokens():
            return _token_error()
        return {
            "data": [
                {
                    "quota_usage": state.quota_usage,
                    "config": {"quota_total": state.quota_limit, "quota_duration": 86400},
                }
            ]
        }

    @graph_router.get("/{item_id}")
    async def get_item(request: Request, item_id: str, access_token: str, fields: str = ""):
        if access_token not in state.all_tokens():
            return _token_error()
        container = state.containers.get(item_id)
        if container is not None:
            if container.status == "ERROR":
                return {"status_code": "ERROR"}
            if container.polled == 0:
                container.polled += 1
                return {"status_code": "IN_PROGRESS"}
            return {"status_code": "FINISHED"}
        post = state.find_media(item_id)
        if post is not None:
            media_base = str(request.base_url).rstrip("/") + "/graph"
            return _serialize(post, media_base)
        return JSONResponse(
            {"error": {"message": "Unsupported get request.", "code": 100}}, status_code=400
        )

    router.include_router(www_router)
    router.include_router(api_router)
    router.include_router(graph_router)
    return router, state


def create_app(state: State | None = None) -> FastAPI:
    """A standalone app covering /www, /api, /graph — what the contract tests run against."""
    router, built_state = build_router(state)
    app = FastAPI(title="Instagram mock", docs_url=None, redoc_url=None)
    app.include_router(router)
    app.state.mock = built_state
    return app
