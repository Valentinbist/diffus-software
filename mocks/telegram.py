"""Mock of the Telegram Bot API, the surface `TelegramSink` calls.

Stands in for `https://api.telegram.org`, mounted here at `/telegram`:

- `POST /telegram/bot{token}/{method}` for `sendPhoto`, `sendVideo`,
  `sendMediaGroup` (multipart) — every call is recorded (chat_id, caption,
  parse_mode, the file field names and sizes, and the `media` JSON for a
  group) so a human or a test can see what "went out" without a real chat.
- `GET /telegram/_calls` — the recorded calls.

Bot token check: an unknown token maps to Telegram's own 401 shape. Unknown
method: Telegram's own 404 shape. A `MOCK_TELEGRAM_RATE_LIMIT_EVERY` knob
answers every Nth call with Telegram's own 429 shape instead, to exercise
`TelegramSink`'s retry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

DEFAULT_BOT_TOKEN = "mock-bot-token"  # a mock credential, not a real secret
BOT_TOKEN_ENV = "MOCK_TELEGRAM_BOT_TOKEN"
RATE_LIMIT_ENV = "MOCK_TELEGRAM_RATE_LIMIT_EVERY"
KNOWN_METHODS = {"sendPhoto", "sendVideo", "sendMediaGroup"}


@dataclass
class Call:
    method: str
    chat_id: str
    caption: str | None
    parse_mode: str | None
    files: dict[str, int]  # field name -> byte size
    media: str | None  # the raw `media` JSON string, for sendMediaGroup
    message_id: int  # 0 for a rate-limited attempt: no message was ever sent
    status_code: int  # 200 or 429 — a rate-limited attempt is recorded too


@dataclass
class State:
    bot_token: str = DEFAULT_BOT_TOKEN
    rate_limit_every: int = 0
    calls: list[Call] = field(default_factory=list)
    attempt_counter: int = 0
    message_counter: int = 0

    def seed(self) -> None:
        self.calls.clear()
        self.attempt_counter = 0
        self.message_counter = 0

    def as_state_dict(self) -> dict:
        return {
            "bot_token_set": bool(self.bot_token),
            "rate_limit_every": self.rate_limit_every,
            "call_count": len(self.calls),
            "attempts": self.attempt_counter,
        }


def build_router(state: State | None = None) -> tuple[APIRouter, State]:
    if state is None:
        state = State(
            bot_token=os.environ.get(BOT_TOKEN_ENV, DEFAULT_BOT_TOKEN),
            rate_limit_every=int(os.environ.get(RATE_LIMIT_ENV, "0")),
        )
        state.seed()

    router = APIRouter(prefix="/telegram")

    @router.post("/bot{token}/{method}")
    async def bot_method(token: str, method: str, request: Request):
        if token != state.bot_token:
            return JSONResponse(
                {"ok": False, "error_code": 401, "description": "Unauthorized"}, status_code=401
            )
        if method not in KNOWN_METHODS:
            return JSONResponse({"ok": False, "description": "Not Found"}, status_code=404)

        state.attempt_counter += 1
        rate_limited = (
            state.rate_limit_every > 0 and state.attempt_counter % state.rate_limit_every == 0
        )

        form = await request.form()
        files: dict[str, int] = {}
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                content = await value.read()
                files[key] = len(content)

        def text_field(name: str) -> str | None:
            value = form.get(name)
            return str(value) if value is not None else None

        message_id = 0
        if not rate_limited:
            state.message_counter += 1
            message_id = state.message_counter

        # Every attempt is recorded, rate-limited or not — a human (or a
        # test) inspecting /telegram/_calls should see the whole retry
        # sequence, not just the message that eventually went out.
        call = Call(
            method=method,
            chat_id=text_field("chat_id") or "",
            caption=text_field("caption"),
            parse_mode=text_field("parse_mode"),
            files=files,
            media=text_field("media"),
            message_id=message_id,
            status_code=429 if rate_limited else 200,
        )
        state.calls.append(call)

        if rate_limited:
            return JSONResponse(
                {"ok": False, "error_code": 429, "parameters": {"retry_after": 1}},
                status_code=429,
            )
        return {
            "ok": True,
            "result": {"message_id": call.message_id, "chat": {"id": call.chat_id}},
        }

    @router.get("/_calls")
    async def get_calls():
        return [
            {
                "method": c.method,
                "chat_id": c.chat_id,
                "caption": c.caption,
                "parse_mode": c.parse_mode,
                "files": c.files,
                "media": c.media,
                "message_id": c.message_id,
                "status_code": c.status_code,
            }
            for c in state.calls
        ]

    return router, state


def create_app(state: State | None = None) -> FastAPI:
    router, built_state = build_router(state)
    app = FastAPI(title="Telegram mock", docs_url=None, redoc_url=None)
    app.include_router(router)
    app.state.mock = built_state
    return app
