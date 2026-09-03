# Architecture

The connector is the first bounded context of the association's digital
backbone: **crossposting** — poll a source, fan out each new post to a set of
destinations, and show what happened. Instagram → Telegram is the only pairing
wired today; the model no longer assumes it.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| IG access | **Business Login for Instagram** (`graph.instagram.com`, scope `instagram_business_basic`) | Own accounts, no Facebook Page dependency. Basic Display API is dead. |
| Tokens | Long-lived (60d); `Token.needs_refresh()` says refresh after **50 days** or within 7 of expiry | #1 cause of silent death. Refresh rides the sync cadence (see sharp edges). |
| New posts | **Poll** `GET /{ig-user-id}/media` | IG webhooks are unreliable for new media |
| Storage | **Postgres** (SQLAlchemy 2.0 async + Alembic + asyncpg) | Already running compose. Backup = `pg_dump` cron. |
| Exactly-once | one `deliveries` row per `(post_id, sink, address)`, PK-enforced; claimed with `INSERT … ON CONFLICT DO NOTHING … RETURNING` | The core invariant; retry-safe by construction |
| Retries | `Delivery` owns it: a FAILED row is retried on every poll until `Delivery.MAX_ATTEMPTS` (5); manual resend bypasses the cap | Policy lives on the entity, so SQL and the test fakes can't drift |
| Persistence boundary | **Unit of Work** (`UnitOfWork` port, `SqlUnitOfWork`); repositories are bound to its session and never commit | Use cases own their transaction boundaries; one place to hook domain events later |
| Topology | **One process**: poller as an APScheduler job in the FastAPI `lifespan`, `uvicorn --workers 1` (pinned) | One sink doesn't need workers |
| Queue/broker | None | Postgres is enough at this scale |
| Media | Download to tempfile → hand `MediaFile(item, path)` to the sink → delete | IG CDN URLs are short-lived; a file path is the one payload every sink can use |
| Routing | `TELEGRAM_CHAT_IDS` env var → `Destination("telegram", chat_id)` list built in the composition root | Edited twice a year, no CRUD needed |
| UI | Jinja served by FastAPI, German, matching the diffus.space design system | No build step |
| Auth | `HTTPBasic` + `secrets.compare_digest`, creds from env | Needs TLS in front (Caddy) — required anyway for the OAuth redirect URI |

## Domain model

```text
Post          id, source, caption, permalink, media, posted_at
Destination   (sink, address)  value object; text form "telegram:-100…"
Delivery      post_id, destination, status, attempts, sent_at, error
              can_retry() / record_sent() / record_failure() / skip()
Token         source, access_token: AccessToken, external_user_id, expires_at, refreshed_at
              needs_refresh(now)
AccessToken   value object whose repr/str never reveal the secret
Preview       a stored still image per (post_id, media index)
MediaFile     (MediaItem, Path) — what a sink receives
```

Ports (`domain/ports.py`): `PostSource` (has a `source` name, fetches with a
`Token`), `PostSink`, `MediaGateway`, `AuthGateway` (has a `source` name), the
four repositories, and `UnitOfWork` / `UnitOfWorkFactory`.

**Post id rule.** `posts.id` is the primary key and must be unique across
sources. Instagram ids stay bare (existing data). Every *new* source adapter
emits `"<source>:<external id>"` as `Post.id`.

## Schema (4 tables)

```sql
tokens      (source PK, access_token, external_user_id, expires_at, refreshed_at)
posts       (id PK, source, caption, permalink, media JSONB, posted_at, fetched_at)
previews    (post_id, media_index, content_type, data, fetched_at)  PRIMARY KEY (post_id, media_index)
deliveries  (post_id, sink, address, status, attempts, sent_at, error)
             PRIMARY KEY (post_id, sink, address)
```

No `accounts` table: one connection per source. Multi-account would key
`tokens` (and routing) by an account id; that is a schema change, deliberately
not made yet.

## Layout

```text
src/diffus/
  app.py                         # composition root: lifespan builds the graph, starts the scheduler;
                                  # also defines health_router (/healthz)
  shared/                        # what every bounded context uses; contexts never import each other
    config.py                    # pydantic-settings, env-only; read by the composition root and alembic
    db/base.py                   # `Base(DeclarativeBase)`; every context's models inherit from it
    db/session.py                # engine / session factory construction
    scheduler.py                 # start_scheduler(): one AsyncIOScheduler interval job
    presentation/
      auth.py                    # HTTP Basic auth dependency, applied to every route
      display.py                 # German date/time/text formatting shared across contexts
      templates.py                # build_templates(): Jinja2Templates + shared filters
      templates/base.html
  crossposting/                  # first bounded context — poll a source, fan out, show what happened
    domain/                      # entities, value objects, ports, errors — stdlib only
    application/                 # use cases; depend only on domain
      sync_posts.py               #   poll → upsert + previews → claim → DeliverPost, per destination
      deliver.py                  #   DeliverPost: sink registry lookup, deliver, record, commit
      sync_job.py                 #   SyncJob: refresh token, then sync, under one lock; LastRun for the UI
      resend_delivery.py, refresh_token.py, connect_instagram.py
      overview.py, post_detail.py, preview.py     # read side
    infrastructure/
      db/                         # models (Base from shared), repositories (session-bound), uow.py
      instagram/                  # Graph client: PostSource + AuthGateway, source = "instagram"
      telegram/                   # render (HTML captions) + sink (PostSink)
      media/                      # CDN download to tempdir → MediaFile
    presentation/
      services.py                 # typed Services dataclass handed to routes via Depends
      routes.py, display.py, templates/            # context-specific filters + templates
  calendar/                       # second context, in progress
alembic/                          # 0001 initial, 0002 previews, 0003 destinations and sources
```

## Conventions

**Unit of work.** A use case opens `async with self.uow() as uow:` per
persistence boundary. Writes call `uow.commit()` explicitly; reads never
commit. **A unit of work never spans a network call**: load what you need,
leave the block, call the source/sink, open a new block to record the result.
The test fake raises if a block exits with uncommitted writes.

**Adapters don't touch persistence.** The use case loads the `Token` and passes
it to `PostSource.fetch_recent`; adapters get plain values, never repositories
or `Settings`.

**Adding a sink.** New package under `infrastructure/`, implement
`PostSink.deliver(post, address, media)`, register it in the composition root's
`sinks = {"telegram": …, "<name>": …}`, add a label to `display.SINK_LABELS`,
and give it destinations. No domain, schema or route change.

**Adding a source.** Implement `PostSource` (+ `AuthGateway` if it needs OAuth)
with a unique `source` name, emit prefixed post ids, and wire a second
`SyncPosts`/`EnsureFreshToken` pair. The token row is keyed by the name already.

## Bounded contexts (the backbone)

Members, calendar, onboarding and whatever follows are separate bounded
contexts, not more entities in this one.

**Done on 2026-09-03:** the connector package moved to
`src/diffus/crossposting/` and `src/diffus/shared/` was extracted (`config.py`,
DB `Base` + `session.py`, `presentation/auth.py`, `presentation/display.py`,
`presentation/templates.py` + `templates/base.html`, `scheduler.py`). The four
rules that govern every context from here on:

1. A new context is a sibling package under `src/diffus/<context>/`, with the
   same four layers and its own `UnitOfWork`.
2. Shared, context-neutral code lives in `src/diffus/shared/`: settings, the
   DB base, session construction, HTTP Basic auth, the base Jinja template and
   filters, the scheduler bootstrap.
3. Contexts never import each other's `domain/`, `application/` or
   `infrastructure/`. A context that needs another's data gets a port in its
   own domain and an adapter in its own infrastructure; domain events through
   the unit of work's `commit()` come when two contexts need to react to each
   other.
4. One FastAPI app, one Alembic history, one `Services` per context mounted
   under its own router prefix.

Mechanical cost of that move, done: every `connector.` import under `src/` and
`tests/` became `diffus.crossposting.` / `diffus.shared.` / `diffus.`;
`pyproject.toml` `[project] name` and a `uv lock`; the `Dockerfile` uvicorn
target; `alembic/env.py` imports; the comment in `alembic.ini`; `readme.md`.
Compose, Ansible and the CI workflow never referenced the package path, so
they were untouched.

## Sharp edges

- Telegram: 1024-char caption cap (truncate + permalink), ~20 msg/min per
  group, media group max 10.
- Token refresh must run on a timer shorter than the process lifetime. It was
  its own 24h APScheduler job, and since an interval trigger first fires one
  interval after start, a host restarting daily never ran it — the token then
  expired silently at day 60. It now rides the sync cadence
  (`application/sync_job.py`).
- Token refresh failure must page you, not log quietly (still only logs; the UI
  shows it).
- A process killed between the committed `claim` and the committed `save`
  leaves that delivery `PENDING` forever; nothing reaps it yet.
- `--workers 1` is load-bearing: the poller runs in the app process.
- Signal (later): dedicated phone number + `signal-cli`; attachments come from
  `MediaFile.path`.
