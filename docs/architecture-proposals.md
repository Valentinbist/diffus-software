# Instagram → Telegram connector — plan

**v1 scope:** Instagram → Telegram only. FastAPI + basic HTMX UI, HTTP Basic auth, no user
management. Postgres from the start. Signal comes later.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| IG access | **Business Login for Instagram** (`graph.instagram.com`, scope `instagram_business_basic`) | Own accounts, no Facebook Page dependency. Basic Display API is dead. |
| Tokens | Long-lived (60d), refresh on a **50-day** timer, alert on failure | #1 cause of silent death |
| New posts | **Poll** `GET /{ig-user-id}/media` | IG webhooks are unreliable for new media |
| Storage | **Postgres** (SQLAlchemy 2.0 async + Alembic + asyncpg) | Already running compose; avoids SQLite migration papercuts. Backup = `pg_dump` cron. |
| Exactly-once | `deliveries` row per `(post_id, chat_id)` with **UNIQUE constraint** | The core invariant; retry-safe by construction |
| Topology | **One process**: poller as asyncio task in FastAPI `lifespan`, `uvicorn --workers 1` (pinned, commented) | One sink doesn't need workers. Split poller out when Signal arrives. |
| Queue/broker | None | Postgres is enough at this scale |
| Media | Download to tempfile → upload to Telegram → delete | IG CDN URLs are short-lived; don't pass them to Telegram |
| Routing | `config.toml` (`ig_account → [chat_id]`), not the DB | Edited twice a year, no CRUD needed |
| UI | Jinja + HTMX served by FastAPI | No build step; SPA only if ever needed |
| Auth | `HTTPBasic` + `secrets.compare_digest`, creds from env | Needs TLS in front (Caddy/tunnel) — required anyway: OAuth redirect URI must be public HTTPS |

## Schema (4 tables)

```sql
tokens      (id=1 singleton, access_token, expires_at, refreshed_at)
accounts    (ig_user_id, username, last_polled_at, bootstrapped)
posts       (id PK, ig_user_id, permalink, caption, media_json, posted_at, fetched_at)
deliveries  (post_id, chat_id, status, attempts, next_attempt_at, sent_at, error)
             UNIQUE(post_id, chat_id)
```

## Layout

```text
src/connector/
  domain.py           # Post, MediaItem, DeliveryResult
  config.py           # pydantic-settings + config.toml routing
  db/                 # models, session
  sources/instagram.py  # Graph client, token exchange + refresh
  sinks/telegram.py
  render/telegram.py  # HTML, 1024-char caption cap, sendMediaGroup for carousels
  media.py            # download to tempfile
  pipeline.py         # poll → persist → dedupe → send → mark
  api/                # main (lifespan poller), auth, routes, templates/
alembic/
docker-compose.yml    # app + postgres + caddy
config.toml
```

Keep `SourceAdapter`/`SinkAdapter` protocols so Signal is a new module, not a redesign.

## Build order

1. Alembic + schema; `Post` + adapter protocols
2. OAuth callback → stored working long-lived token (verify with manual `GET /me/media`)
3. Poller → `posts` table, **sending disabled**; confirm dedupe across restarts
4. `--mark-seen-only` bootstrap — *before* enabling sends, or first run mirrors all history
5. Telegram sink + renderer, retry/backoff, `429 retry_after` handling
6. HTMX UI: recent posts, delivery status, manual re-send
7. *(later)* Signal: split poller into own process, add `signal-cli-rest-api`

## Sharp edges

- Telegram: 1024-char caption cap (truncate + permalink), ~20 msg/min per group, media group max 10
- Token refresh failure must page you, not log quietly
- Signal (later): dedicated phone number + `signal-cli`, attachments as bytes not URLs
