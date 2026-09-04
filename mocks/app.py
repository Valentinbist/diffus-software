"""One FastAPI app mounting all three mocks, for `uvicorn mocks.app:app`.

- `/graph`, `/api`, `/www` — Instagram (see `mocks/instagram.py`)
- `/kalender` — kalender.digital (see `mocks/kalender.py`)
- `/telegram` — the Telegram Bot API (see `mocks/telegram.py`)
- `GET /` — lists the three, with their real-API equivalents
- `GET /_state` — every mock's in-memory state, as JSON
- `POST /_reset` — reseeds all three from scratch

Run locally with `uv run uvicorn mocks.app:app --port 8100 --reload`, or
`python -m mocks` (see `mocks/__main__.py`); in Docker via
`docker-compose.mocks.yml`, which points the `app` service's
`INSTAGRAM_*`/`KALENDER_DIGITAL_*`/`TELEGRAM_*` settings at this process.
"""

from __future__ import annotations

from fastapi import FastAPI

from mocks import instagram, kalender, telegram


def create_app() -> FastAPI:
    app = FastAPI(title="diffus mocks", docs_url=None, redoc_url=None)

    ig_router, ig_state = instagram.build_router()
    kalender_router, kalender_state = kalender.build_router()
    telegram_router, telegram_state = telegram.build_router()

    app.include_router(ig_router)
    app.include_router(kalender_router)
    app.include_router(telegram_router)

    @app.get("/")
    async def index():
        return {
            "mocks": {
                "instagram": {
                    "stands_in_for": [
                        "https://www.instagram.com (oauth) -> /www",
                        "https://api.instagram.com (oauth) -> /api",
                        "https://graph.instagram.com -> /graph",
                    ],
                },
                "kalender.digital": {
                    "stands_in_for": "https://api.kalender.digital -> /kalender",
                },
                "telegram": {
                    "stands_in_for": "https://api.telegram.org -> /telegram",
                },
            },
            "state": "/_state",
            "reset": "POST /_reset",
        }

    @app.get("/_state")
    async def get_state():
        return {
            "instagram": ig_state.as_state_dict(),
            "kalender": kalender_state.as_state_dict(),
            "telegram": telegram_state.as_state_dict(),
        }

    @app.post("/_reset")
    async def reset():
        ig_state.seed()
        kalender_state.seed()
        telegram_state.seed()
        return {"ok": True}

    return app


app = create_app()
