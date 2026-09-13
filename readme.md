# diffus.space social posting

Polls one Instagram Business account and composes posts of its own, then
publishes both to Telegram and, optionally, back to Instagram — each
channel either automatically or after a manual Freigabe (approval). Single
Python process (FastAPI + APScheduler), Postgres for state, HTTP Basic auth
on every route. Instagram/Telegram is the only pairing wired today; the
model is source/sink agnostic — see [`docs/architecture.md`](docs/architecture.md)
for the design, decisions and how to add a sink, a source, or a new bounded
context.

## Quickstart

1. `cp .env.example .env` and fill it in:
   - Instagram: create a Meta app with **Business Login for Instagram**
     (<https://developers.facebook.com/apps>) and set `IG_APP_ID`, `IG_APP_SECRET`,
     `IG_REDIRECT_URI` (must be a public HTTPS URL registered on the app).
   - Telegram: create a bot via [@BotFather](https://t.me/BotFather), set
     `TELEGRAM_BOT_TOKEN`, add the bot to the target chats, and set
     `TELEGRAM_CHAT_IDS` (comma-separated).
   - Set `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` for the UI.
   - Optionally set `DISPLAY_TIMEZONE` (default `Europe/Berlin`) for the times
     the UI shows. Storage stays UTC.
   - Optionally set `KALENDER_DIGITAL_TOKEN` to also sync the shared room
     calendar from [kalender.digital](https://kalender.digital) and show it
     under **Kalender**: it's the 20 hex characters at the end of that
     calendar's share link (`https://kalender.digital/<token>`). That link is
     editor-level — anyone holding it can edit or delete the whole calendar —
     so treat it like a password. Leave it empty to run without the calendar
     feature; nothing calendar-related is synced, shown, or routable.
   - Set `PUBLIC_BASE_URL` to where this app is itself publicly reachable
     (`https://your.host` in production). Instagram fetches a compose
     wizard's images itself from `PUBLIC_BASE_URL/media/drafts/...` at
     publish time, so it has to be a real public HTTPS URL — Instagram
     cannot reach `http://localhost`. Telegram-only publishing works fine
     locally with the default `http://localhost:8000`; see
     [`docs/development.md`](docs/development.md) for a one-command tunnel
     that lifts that limit for a dev box too.
2. `docker compose up --build` (the dev stack: hot-reloading app + Postgres,
   plus a `web` service that runs `npm ci && npm run watch` into a shared
   volume so the frontend's Vite/TypeScript/htmx build stays current as you
   edit `web/src/`; the image that ships is the `runtime` stage of the same
   Dockerfile, which bakes a production build of `web/` in at image-build time)
3. Open `http://localhost:8000` (behind Basic auth) and click **Instagram
   verbinden** to complete the OAuth flow. The UI is in German, like the
   diffus.space site it belongs to, and has a **Kalender** page alongside
   the Social Posts page when `KALENDER_DIGITAL_TOKEN` is set.

The first sync after connecting only marks existing posts as seen — it never
blasts your entire history into Telegram. New posts found on later polls are
delivered normally.

**After any deploy that changes the Instagram OAuth scope** (e.g. this
round's addition of the publish scope, `instagram_business_content_publish`)
click **Instagram verbinden** again once — a token connected under the old,
narrower scope keeps working for reading, but the compose wizard shows
"Instagram neu verbinden, um Veröffentlichen freizuschalten." until you do.

## Freigabe (approval queue)

Nothing goes out on its own by default. Every post — one composed in the
app or one the poll just found on Instagram — waits on **/freigabe**
("Freigabe" in the nav, with a live count badge) until someone approves
it, per channel:

- A **channel's own auto-publish switch** (**Einstellungen** →
  **Automatisch veröffentlichen**, one checkbox per channel — Instagram and
  each Telegram chat) skips the queue for that channel. It's off for every
  channel by default, so switch on the ones that should go out immediately;
  the rest still queue.
- A **composed post** is approved as a whole: pick its targets on
  `/freigabe` and click **Freigeben** (or **Ablehnen** to discard it).
- A **post the poll found on Instagram** queues per target: approve the
  Telegram chats it should go to, or reject it outright.
- A retried delivery (one that already failed once) is never re-queued — it
  keeps retrying on its own schedule regardless of the switch, since it was
  already approved.

`/freigabe` also keeps a **Verlauf** (history) below the queue: every past
decision — approved, rejected, or auto-published, drafts and polled posts
alike — newest first, so the queue itself only ever shows what is still
open.

## The wizard

One flow, three steps — **Termin → Post → Vorschau** — behind a single
prominent entry point: the call-to-action button in the sidebar (the top
bar on phones), **Neues Event erstellen** with the calendar context on,
**Neuer Post** without it
(there is no Termin step to promise then). It is the only "Neu" anywhere in
the UI; Social Posts and the calendar page have none of their own. Each of
the wizard's first two steps is skippable. All three are ordinary pages that
also open as one modal on desktop, with a step indicator (`1 Termin · 2 Post
· 3 Vorschau`) marking where you are.

- **1 Termin** (`/neu`, or `?post={id}` from a post's page's "Termin
  anlegen"): prefills a title (the caption's first line) and a date (a
  mention like "12.9." in the caption, or the posted day otherwise) when
  started from a post, or blank defaults otherwise; writes the event
  straight into kalender.digital. **Ohne Termin weiter** skips to step 2.
  Without the calendar context, the cta goes straight to step 2 —
  there is no Termin step to show. Started from a post, step 1 links that post to
  the new event itself and the wizard is done: it finishes on the event
  page rather than continuing to step 2.
- **2 Post** (`/posts/new`, reached with `?event={id}` after step 1 or from
  an event's page's "Post erstellen"): a caption prefilled from the linked
  event when there is one (date, time, room, description), up to 10 images,
  and a choice of targets — Instagram and/or any Telegram chat. **Ohne Post
  fertig** skips to the event page.
- **3 Vorschau** (`/posts/new/{draft}`): review, then publish. If every
  chosen target is on auto-publish it goes out immediately; otherwise it
  lands on `/freigabe`. A Telegram-only post becomes a first-class
  `diffus:<draft id>` post in the feed, exactly like an Instagram one, and —
  when it was started from an event — is linked back to it automatically.

A post polled from Instagram carries an "Instagram ✓" line (linking to its
permalink) alongside its Telegram deliveries, in the post modal and the
overview — it was never "delivered" there by the app, but the fact belongs
on the same list as the channels the app did send it to.

Instagram's connection status, the per-channel auto-publish switches, the
`PUBLIC_BASE_URL` readiness hint, and a view into the automation itself (how
often the Instagram and calendar syncs run, when the next one fires, and
each one's last few runs) all live on their own page, **/einstellungen**
("Einstellungen", in the nav); Social Posts itself keeps only a one-line
attention notice pointing there when something needs it.

## Small pleasures

Small, dry touches that don't change what the app does (round 7):

- A one-line **greeting** ("Guten Morgen.", "Nachtschicht?") above the Social Posts heading, at the right hour.
- **Milestones** ("Das war Post Nummer 100.") called out the moment a round number is crossed, on Social Posts and Freigabe.
- An **activity heatmap** of the last 16 weeks under the Social Posts feed.
- An **inbox-zero line** on Freigabe: how long the queue has sat empty, and whether that's a record.
- A **reaction-time line** on Freigabe's Verlauf: how fast things get decided, on average and at best.
- Per-job **streaks** on Einstellungen: consecutive error-free syncs, and where the last one broke.
- A blurred **backdrop** of the newest post behind every page, everywhere in the app.
- The page **idles into a subtle blur** after a stretch with no interaction.
- A touch of **film grain** over the whole page.
- The Freigabe nav badge gets a soft **breathing** animation while something is waiting.

## Dev setup

Python 3.14 + [uv](https://docs.astral.sh/uv/), plus a separate frontend build
(Vite + TypeScript + htmx in `web/`):

```sh
uv sync                            # .venv + everything, dev tools included
cd web && npm ci && npm run build  # the frontend; `uv run` never touches it

uv run ruff check . && uv run ty check && uv run pytest -q
```

Or entirely in Docker — `docker-compose.yml` builds the `dev` stage and
bind-mounts `src/`, so edits reload without a rebuild:

```sh
docker compose up --build          # the dev stack on http://localhost:8000
docker compose exec app pytest -q  # tests inside the container
```

There are three ways to run the stack — against the **real** services, against
local **mocks** (nothing leaves the machine), or behind a public **tunnel** (so
Instagram publishing works from a laptop) — and VS Code tasks for each. Which
to use when, what is safe to click in each, how to reconnect Instagram, and how
to run the Postgres-backed tests: see
**[`docs/development.md`](docs/development.md)**.

The `Dockerfile` is staged: `deps` → `builder` → `runtime` (what CI pushes to
GHCR: no uv, no sources, runs as the unprivileged `app` user) and `deps` → `dev`
(dev tools + editable install + `--reload`).

## Layers

```text
domain          entities, value objects (Destination, AccessToken), ports incl. UnitOfWork; stdlib only
application     use cases (sync, deliver, sync job, connect, refresh, resend, overview); depend only on domain
infrastructure  Postgres (SQLAlchemy async, SqlUnitOfWork), Instagram Graph client, Telegram sink, media downloader
presentation    typed Services, routes, Jinja templates
```

`src/diffus/app.py` is the composition root: it builds the object graph and wires
the FastAPI app + scheduler. `src/diffus/shared/` holds what's shared across
bounded contexts — settings, the DB base, HTTP Basic auth, the base Jinja
template, the scheduler bootstrap. See
[`docs/architecture.md`](docs/architecture.md) for the full layout.

## Deployment

One VPS running Docker. Host config is an Ansible playbook; app deploys are a
GitHub Actions pipeline. Neither requires you to edit anything over SSH — if you
want to change the host, change [`infra/ansible/playbook.yml`](infra/ansible/playbook.yml)
and re-run it.

```text
infra/ansible/    host config: docker, deploy user, ufw, sshd hardening, nightly pg_dump
infra/compose/    the production stack that runs on the box: app + postgres + caddy
.github/workflows/ci-cd.yml   check -> build -> deploy
```

Strato has no public API or Terraform provider, so the box itself is created
once by hand in their panel. Everything after that is declarative.

### One-time setup

1. **Order the VPS** (Debian), and point an A record for your domain at it.
2. **Configure the host.** Copy `infra/ansible/inventory.example.ini` to
   `inventory.ini`, fill in the hostname and the public keys — *your* key and
   the CI deploy key, because the playbook disables password auth:

   ```sh
   cd infra/ansible
   ansible-galaxy collection install -r requirements.yml
   ansible-playbook playbook.yml          # first run: ansible_user=root
   ```

   Then switch `ansible_user` to `deploy` in the inventory for all later runs.
3. **Add the GitHub secrets** below (Settings → Secrets → Actions).

### GitHub secrets

| Secret | What it is |
| --- | --- |
| `DEPLOY_HOST` | Server IP or hostname |
| `DEPLOY_SSH_KEY` | Private half of the CI deploy key |
| `SSH_KNOWN_HOSTS` | `ssh-keyscan -t ed25519 <host>` output. Optional, but without it the first connection is trust-on-first-use |
| `APP_DOMAIN` | FQDN Caddy issues a certificate for |
| `POSTGRES_PASSWORD` | Database password |
| `IG_APP_ID`, `IG_APP_SECRET`, `IG_REDIRECT_URI` | Instagram app credentials |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` | Telegram bot and target chats |
| `KALENDER_DIGITAL_TOKEN` | kalender.digital share-link token; leave the secret empty (or unset) to deploy without the calendar feature |
| `BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD` | UI credentials |
| `PUBLIC_BASE_URL` | *Not its own secret* — the pipeline derives it as `https://${APP_DOMAIN}` and writes it to `.env` itself; nothing to add here |

### Deploying

Push to `main`, or run the workflow manually. The pipeline lints, type-checks
and tests; builds the image and pushes it to GHCR tagged with the commit SHA;
ships the compose files; writes `.env` on the host from the secrets above; then
`docker compose pull && up -d`. It finally polls `/healthz` over HTTPS and fails
the run if the new version isn't serving.

`.env` on the host is written *only* by the pipeline. Editing it in place means
the next deploy silently reverts you.

### Operational notes

- **TLS** is Caddy with automatic Let's Encrypt, which is what makes
  `IG_REDIRECT_URI` a valid public HTTPS URL and stops Basic auth travelling in
  cleartext.
- **Postgres is never published to the host interface** — it is reachable only
  over the compose network. This matters because Docker's iptables rules bypass
  ufw, so a published port would be exposed regardless of the firewall.
- **Post images live in Postgres.** Instagram's CDN links expire, so each sync
  stores a copy of every still image in the `previews` table while the link is
  fresh, and the UI serves them from `/posts/<id>/media/<n>`. A few hundred KB
  per image; it grows with the number of posts, not with time.
- **Backups** are a nightly `pg_dump` to `/opt/connector/backups`, kept 14 days.
  That covers a bad migration, not a lost server; ship them off-box if the data
  matters to you.
- **`--workers 1` is still load-bearing.** The poller runs inside the app
  process, so a second worker means two pollers racing.
