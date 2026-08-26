# Instagram → Telegram connector

Polls one Instagram Business account and fans out new posts to N Telegram chats.
Single Python process (FastAPI + APScheduler), Postgres for state, HTTP Basic
auth on every route. No Signal support in v1 — see
[`docs/architecture-proposals.md`](docs/architecture-proposals.md) for the
full design and decisions.

## Quickstart

1. `cp .env.example .env` and fill it in:
   - Instagram: create a Meta app with **Business Login for Instagram**
     (<https://developers.facebook.com/apps>) and set `IG_APP_ID`, `IG_APP_SECRET`,
     `IG_REDIRECT_URI` (must be a public HTTPS URL registered on the app).
   - Telegram: create a bot via [@BotFather](https://t.me/BotFather), set
     `TELEGRAM_BOT_TOKEN`, add the bot to the target chats, and set
     `TELEGRAM_CHAT_IDS` (comma-separated).
   - Set `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` for the UI.
2. `docker compose up --build`
3. Open `http://localhost:8000` (behind Basic auth) and click **Connect
   Instagram** to complete the OAuth flow.

The first sync after connecting only marks existing posts as seen — it never
blasts your entire history into Telegram. New posts found on later polls are
delivered normally.

## Dev setup

Python 3.14 + [uv](https://docs.astral.sh/uv/):

```sh
uv sync            # creates .venv, installs everything incl. dev tools
uv run pytest      # tests run against in-memory fakes (no DB, no network)
uv run ruff check .
uv run ty check
```

## Layers

```text
domain          entities + ports (protocols); stdlib only, no framework deps
application     use cases (sync, connect, refresh, resend, overview); depends only on domain
infrastructure  Postgres (SQLAlchemy async), Instagram Graph client, Telegram bot client, media downloader
presentation    FastAPI app, routes, HTTP Basic auth, Jinja templates — the composition root
```
