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
| Routing | `TELEGRAM_CHAT_IDS` env var (comma-separated chat ids), not the DB | Edited twice a year, no CRUD needed |
| UI | Jinja + HTMX served by FastAPI | No build step; SPA only if ever needed |
| Auth | `HTTPBasic` + `secrets.compare_digest`, creds from env | Needs TLS in front (Caddy/tunnel) — required anyway: OAuth redirect URI must be public HTTPS |

## Schema (3 tables, single account)

```sql
tokens      (id=1 singleton, access_token, ig_user_id, expires_at, refreshed_at)
posts       (id PK, caption, permalink, media JSONB, posted_at, fetched_at)
deliveries  (post_id, chat_id, status, attempts, sent_at, error)
             PRIMARY KEY (post_id, chat_id)
```

No `accounts` table: v1 targets exactly one Instagram account (Business Login
for Instagram), so there is nothing to key it against — `tokens` is a
singleton row. Fan-out to multiple Telegram chats is env-configured routing,
not a DB relationship. Retries are attempt-counted (`attempts`, capped at 5),
not scheduled — there is no `next_attempt_at`; a failed delivery is simply
retried on every poll cycle until the cap is hit.

## Layout

```text
src/connector/
  config.py                     # pydantic-settings, env-only (no config.toml)
  domain/                       # entities, ports (protocols), errors — stdlib only
  application/                  # use cases: sync_posts, connect_instagram,
                                 #   refresh_token, resend_delivery, overview
  infrastructure/
    db/                         # SQLAlchemy models, session, repositories
    instagram/                  # Graph client: PostSource + AuthGateway
    telegram/                   # render (HTML captions) + sink (PostSink)
    media/                      # CDN download to tempdir
  presentation/
    app.py                      # composition root: FastAPI lifespan builds
                                 #   the object graph, starts the scheduler
    jobs.py                     # SyncJob: refresh token, then sync (one timer)
    routes.py, auth.py          # HTTP Basic auth on every route except /healthz
    templates/                  # Jinja, no build step, no external assets
alembic/
docker-compose.yml    # app + postgres (dev; production stack lives in infra/)
infra/                # ansible host config + production compose
```

Keep `PostSource`/`PostSink`/`AuthGateway` protocols (`domain/ports.py`) so
Signal is a new `infrastructure/` adapter, not a redesign.

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
- Token refresh must run on a timer shorter than the process lifetime. It was
  its own 24h APScheduler job, and since an interval trigger first fires one
  interval after start, a host restarting daily never ran it — the token then
  expired silently at day 60. It now rides the sync cadence (`presentation/jobs.py`).
- Token refresh failure must page you, not log quietly (still only logs)
- Signal (later): dedicated phone number + `signal-cli`, attachments as bytes not URLs
