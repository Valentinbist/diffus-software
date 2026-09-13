# Development

How to run this app locally, which of the three stack modes to use, and — the
part that bites — which flows have real side effects and which are safe to
poke at. For what the code *is*, see [`architecture.md`](architecture.md).

## First run

```sh
cp .env.example .env     # then fill it in — see the readme's Quickstart
uv sync                  # .venv + every dependency, dev tools included
cd web && npm ci         # the frontend build (Vite + TypeScript + htmx)
npm run build
```

The frontend is a separate build step; `uv run` never touches it. Without a
build the app still boots and the tests still pass — `shared/presentation/assets.py`
logs one warning and falls back to unhashed asset names — but you get no real
CSS and no desktop modals until `npm run build` has run once.

## The three ways to run the stack

| Mode | Command | Talks to | Use it when |
|---|---|---|---|
| **Real** | `docker compose up --build` | the real Instagram, kalender.digital and Telegram | working on the app against real data |
| **Mocks** | `docker compose -f docker-compose.yml -f docker-compose.mocks.yml up --build` | local fakes on `:8100`, nothing leaves the machine | trying a flow end to end without consequences |
| **Tunnel** | `scripts/dev-tunnel.sh` | real services, plus a public https address for this laptop | testing Instagram publishing |

In VS Code all three are under **Run Task** (`.vscode/tasks.json`), along with
`Backend: stop`, `Backend: logs (app)`, `Checks: ruff + ty + pytest` and
`Frontend: build`.

**They are mutually exclusive.** All three use the compose project
`diffus-software` and publish `:8000`, so starting one recreates the others'
containers; `--remove-orphans` is what tears the mocks container down when you
switch back. Their databases are separate volumes (`pgdata` for real and
tunnel runs, `pgdata_mocks` for mock runs), so switching never mixes mock data
into your real synced posts — but you cannot run two at once.

## What is safe to try, and what is not

The app exists to publish things. Several flows really do reach the outside
world, so it is worth knowing which is which before clicking around a stack
pointed at real services.

| Action | Against real services | Against the mocks |
|---|---|---|
| Sync posts / calendar | reads only — safe | safe |
| Create a draft, preview it | local only — safe | safe |
| **Approve in Freigabe** | **sends to the real Telegram chat** | recorded at `/telegram/_calls` |
| **Publish with Instagram ticked** | **posts publicly to the account** | recorded in the mock's media list |
| **"Termin anlegen"** | **writes into the shared kalender.digital calendar** | writes to the mock only |

Two things make the real stack forgiving by default:

- **Nothing auto-publishes.** `channel_settings` starts empty, so every
  channel is off and everything waits in Freigabe until a human approves it.
  Check with `select * from channel_settings;` — no rows means nothing can go
  out on its own.
- **The first sync only marks posts seen.** An empty `posts` table forces
  `mark_seen_only`, so connecting an account never blasts its back catalogue.

There is also a genuinely safe way to test the Instagram publish path without
posting: create a media *container* and stop there. A container is not a post
— it is Meta fetching your image and validating it — and it expires by itself
after 24 hours. See "Testing Instagram publishing" below.

## Testing against the mocks

```sh
docker compose -f docker-compose.yml -f docker-compose.mocks.yml up --build
```

The override adds a `mocks` service (`mocks/app.py`, the same `dev` image as
`app`) and repoints the app's Instagram, kalender.digital and Telegram
settings at it. Compose `environment` beats `env_file`, so this needs no edit
to `.env`.

What each mock stands in for:

- **Instagram** (`/graph`, `/api`, `/www`) — OAuth whose authorize endpoint
  hands back a code immediately (no login screen), four seeded posts (an
  image, a 3-image carousel, a video, and one whose caption names the date of
  the calendar mock's "Siebdruck-Nachmittag", so the link-suggestion heuristic
  has an exact match), and a working publish path: container creation,
  polling to `FINISHED`, and `media_publish`. Container creation really
  fetches the image from the app's own public media route, so publishing
  against the mock exercises that whole path.
- **kalender.digital** (`/kalender`) — the seven real sub-calendars and an
  agenda seeded *relative to today* (weekly Stammtisch and Plenum, a one-day
  and a two-day whole-day event, one crossing midnight), plus `create_event`.
- **Telegram** (`/telegram`) — records every `sendPhoto`/`sendVideo`/
  `sendMediaGroup` instead of sending it.

Inspect and control them:

| URL | What |
|---|---|
| `http://localhost:8100/_state` | all three mocks' state as JSON |
| `http://localhost:8100/telegram/_calls` | every Telegram call the app made |
| `POST http://localhost:8100/_reset` | reseed everything |

Knobs (env vars on the `mocks` service): `MOCK_INSTAGRAM_QUOTA` (default 100,
publishing past it fails like Meta's real limit), `MOCK_KALENDER_TOKEN`,
`MOCK_TELEGRAM_BOT_TOKEN`, `MOCK_TELEGRAM_RATE_LIMIT_EVERY` (default 0; every
Nth call answers 429, to exercise `TelegramSink`'s retry).

To run the mocks alone: `uv run uvicorn mocks.app:app --port 8100 --reload`,
or `uv run python -m mocks`. `mocks/` sits outside `src/diffus`, is never
imported by it, and only the `dev` image ships it. `tests/mocks/` runs the
*real* adapters against these mocks, which is what stops the two drifting
apart.

## Testing Instagram publishing

Instagram's `/media` endpoint has Meta's own servers fetch the draft image
from `PUBLIC_BASE_URL`. They can reach neither `http://localhost` nor this
app's Basic auth, which makes this the one flow that needs a real public
https address. One command:

```sh
scripts/dev-tunnel.sh
```

It opens an ngrok tunnel to `:8000`, waits for the URL, and starts the stack
with `PUBLIC_BASE_URL` pointed at it (`docker-compose.tunnel.yml`). Ctrl+C
stops both. The URL is passed at startup rather than read from `.env` because
a free tunnel's hostname changes every run — which also means **restarting the
tunnel means restarting the app**. Already have a tunnel (a reserved ngrok
domain, `cloudflared tunnel --url http://localhost:8000`, a Tailscale funnel)?
Export `PUBLIC_BASE_URL` and the script uses it instead of starting its own.

To prove a tunnel is good enough for Meta **without publishing anything**,
create a container and poll it:

```sh
# 1. create a draft in the UI, then read its id and key
docker compose exec postgres psql -U connector -d connector \
  -c "select id, public_key from post_drafts order by created_at desc limit 1;"

# 2. hand Meta the tunnelled URL — this fetches the image, it does not post
curl -s -X POST "https://graph.instagram.com/v21.0/<ig-user-id>/media" \
  --data-urlencode "image_url=<PUBLIC_BASE_URL>/media/drafts/<draft>/0?key=<public_key>" \
  --data-urlencode "access_token=<token>"

# 3. poll until FINISHED — that means Meta fetched and accepted it
curl -s -G "https://graph.instagram.com/v21.0/<container-id>" \
  --data-urlencode "fields=status_code" --data-urlencode "access_token=<token>"
```

`FINISHED` means the whole path works. Stop there and the container expires on
its own; `quota_usage` on `/content_publishing_limit` stays where it was,
confirming nothing was posted.

Telegram-only publishing needs none of this and works against plain
`http://localhost:8000`.

## Reconnecting Instagram

The token lives in the `tokens` table, not in `.env` — the `IG_TOKEN` key some
`.env` files still carry is dead config the app ignores. The supported way to
refresh it is clicking **Instagram verbinden** on `/einstellungen`, which runs
the OAuth flow and records the granted scopes.

That `scopes` column is what gates publishing: `Token.can_publish` looks for
`instagram_business_content_publish` in it. A token connected before that
scope existed reads fine but cannot publish, and the settings page says so
until you reconnect. To check what a token can actually do:

```sh
curl -s -G "https://graph.instagram.com/v21.0/me" \
  --data-urlencode "fields=id,username" --data-urlencode "access_token=<token>"
# publish scope present? this returns data instead of an error:
curl -s -G "https://graph.instagram.com/v21.0/<ig-user-id>/content_publishing_limit" \
  --data-urlencode "access_token=<token>"
```

## Checks

```sh
uv run ruff check . && uv run ty check && uv run pytest -q
cd web && npm run check && npm run build
```

That is what CI runs. The suite uses in-memory fakes — no database, no
network — except for `tests/crossposting/test_sql_repositories.py`, which is
skipped unless `TEST_DATABASE_URL` is set. To run those against a real
Postgres (the dev one is not published on the host, so this runs inside the
compose network, on a throwaway database):

```sh
docker compose exec -T postgres createdb -U connector connector_test
U=postgresql+asyncpg://connector:connector@postgres:5432/connector_test
docker compose run --rm --no-deps -e DATABASE_URL=$U app alembic upgrade head
docker compose run --rm --no-deps -e DATABASE_URL=$U -e TEST_DATABASE_URL=$U \
  app pytest tests/crossposting/test_sql_repositories.py -q
```

They exist because the fakes cannot catch everything: an ordering bug that
violated a foreign key slipped past a fully green suite once, because no fake
has foreign keys.

## Gotchas

- **The stacks are mutually exclusive** — same compose project, same `:8000`.
- **`PUBLIC_BASE_URL` is read at startup.** A new tunnel URL means restarting
  the app, which `scripts/dev-tunnel.sh` handles by starting them together.
- **Migrations run on container start** (`docker/entrypoint.sh` runs
  `alembic upgrade head` before uvicorn), so a new migration needs a restart,
  not just a reload.
- **`uv run pytest` on the host uses fakes only.** Green tests do not prove
  the SQL is right; see the Postgres-gated suite above.
- **The `dev` image is uid/gid 1000.** On Linux, pass
  `--build-arg UID=$(id -u) --build-arg GID=$(id -g)` if yours differs, so the
  bind mounts stay writable.
- **The service worker caches `/static/` in your browser.** Hashed files
  under `/static/dist/assets/` are cache-first (safe: a rebuild renames them);
  the manifest, icons and `offline.html` are network-first, so an edit shows
  on the next load — except the copy of `offline.html` the worker precaches
  for offline use, which refreshes only with a new worker, i.e. per
  `npm run build` or per start of the `web` service (`__BUILD_ID__` is fixed
  for one `vite build --watch`). Pages are never cached. While working on
  `sw.ts`, tick "Update on reload" under DevTools → Application → Service
  Workers, or unregister it there.
