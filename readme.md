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
4. On a phone, pick **Zum Home-Bildschirm** / **App installieren** from the
   browser menu: the site is an installable web app (manifest, icons and a
   service worker), so it opens in its own window with an icon, and a failed
   page load shows a German offline page instead of the browser's. Nothing
   else is cached — every page still comes from the server, behind Basic
   auth, so expect the password prompt once after the browser has restarted.

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
uv run prek install                # ruff (fix + format) and ty as a git hook on every commit
cd web && npm ci && npm run build  # the frontend; `uv run` never touches it

uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
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

Production runs on a Proxmox box at home: one Debian VM (made by Terraform and
cloud-init) running [Coolify](https://coolify.io), which runs the app and its
Postgres. A Cloudflare Tunnel is the only way in, so nothing is open at home.
GitHub Actions tests the code and builds the image; Coolify runs it. There are
no backups: if the VM dies, the data goes with it.

```text
.github/workflows/ci-cd.yml        check + infra -> build (image to GHCR) -> deploy (via the Coolify API)
scripts/coolify-deploy.sh          the deploy step: set image tag, deploy, wait for the result
infra/terraform/                   Cloudflare (tunnel, DNS, Access, rulesets) and the Proxmox VM
infra/cloud-init/                  first-boot config of the VM: ssh, cloudflared, Coolify installer
```

Two Coolify resources, both in one project and on the same server:

- **PostgreSQL**: a Coolify-managed database.
- **The app**: an application with the *Docker Image* build pack, pulling
  `ghcr.io/valentinbist/diffus-software`. CI sets the tag to the commit SHA on
  every deploy, so Coolify always shows which commit is running.

The app is at `https://<app hostname>`. The Coolify dashboard is at
`https://<coolify hostname>`, behind Cloudflare Access: only the admin emails
pass (login by email code), plus CI with a service token.

### One-time setup

1. **Accounts and tokens.** Terraform is applied by hand from a laptop
   (`terraform` 1.14, see `.tool-versions`); CI only checks its syntax.
   - Cloudflare: an API token for Terraform with: Account → Cloudflare Tunnel
     Edit, Access: Apps and Policies Edit, Access: Service Tokens Edit;
     Zone → DNS Edit, Zone WAF Edit, Single Redirect Edit.
   - Proxmox: an API token (*Datacenter → Permissions → API Tokens*) with rights
     on the node and the datastores, content type **Snippets** and **Import**
     enabled on the `local` datastore (*Datacenter → Storage*), and the laptop's
     SSH key in root's `authorized_keys` on the node (the provider uploads the
     cloud-init file over SSH).
2. **Apply Terraform.**

   ```sh
   cd infra/terraform
   cp terraform.tfvars.example terraform.tfvars  # hostnames, node, ssh keys, ...
   export CLOUDFLARE_API_TOKEN=… PROXMOX_VE_ENDPOINT=… PROXMOX_VE_API_TOKEN=…
   terraform init
   terraform apply
   ```

   This creates the tunnel, DNS records, the Access application, the zone
   rules and the VM. The VM installs cloudflared and Coolify on first boot;
   give it a few minutes. The state stays in `infra/terraform/terraform.tfstate`
   on that laptop (gitignored, it holds the tunnel secret). Losing it is not
   fatal: import the resources again, or delete and re-create them.
3. **First boot.** Open `http://<vm ip>:8000` (`terraform output vm_ipv4`) from
   the LAN **immediately** and register: the first visitor becomes Coolify's
   admin. Then *Settings*: set the instance domain to `http://<coolify hostname>`
   and, under *Advanced*, turn on **API Access**.
4. **Image access.** GHCR packages start out private, even for a public repo.
   Either make `diffus-software` public (GitHub → Packages → Package settings),
   or run `docker login ghcr.io` on the VM once with a token that has
   `read:packages`.
5. **Database.** *+ New → Database → PostgreSQL 17*, then start it. Copy its
   **internal** Postgres URL and change the scheme to `postgresql+asyncpg://`.
   That is `DATABASE_URL`. Leave "Make it publicly available" off.
6. **App.** *+ New → Docker Image*, image `ghcr.io/valentinbist/diffus-software`,
   tag `latest` for the first start. Then set:

   | Setting | Value |
   | --- | --- |
   | Domain | `http://<app hostname>` (port 8000 is the exposed port) |
   | Health check | enabled, path `/healthz`, port `8000`, start period `60`s |
   | Environment | everything in `.env.example`, with `DATABASE_URL` from step 5, `PUBLIC_BASE_URL=https://<app hostname>` and `IG_REDIRECT_URI=https://<app hostname>/oauth/callback` |

   The domain is `http://` on purpose: Cloudflare terminates TLS, and with
   `https://` Traefik would try to get its own certificate and redirect-loop
   behind the tunnel. The URLs the app hands out stay `https`.

   Leave the mocks overrides (`*_API_BASE`, `INSTAGRAM_*`, `PUBLISH_ALLOW_HTTP`)
   unset, so they keep their real defaults. Turn off any automatic deploy on
   push: CI triggers deploys after the checks pass. The app UUID is in its URL
   in Coolify.
7. **API token.** *Keys & Tokens → API tokens*, with `deploy` and `write`
   permissions (setting the image tag is a write).
8. **GitHub secrets** (Settings → Secrets → Actions, environment `production`):

   | Secret | What it is |
   | --- | --- |
   | `COOLIFY_URL` | Base URL of the Coolify dashboard, `https://<coolify hostname>` |
   | `COOLIFY_TOKEN` | The API token from step 7 |
   | `COOLIFY_APP_UUID` | The app's UUID |
   | `CF_ACCESS_CLIENT_ID` | `terraform output ci_access_client_id` |
   | `CF_ACCESS_CLIENT_SECRET` | `terraform output -raw ci_access_client_secret` |
   | `APP_DOMAIN` | The app's hostname, without `https://`. Used only for the final `/healthz` check |

The app's own credentials (Instagram, Telegram, kalender.digital, Basic auth)
live only in Coolify's environment tab, not in GitHub.

### Deploying

Push to `main`, or run the workflow manually. The pipeline lints, type-checks
and tests; builds the image and pushes it to GHCR tagged with the commit SHA
(and `latest`); sets that tag on the Coolify app and triggers a deployment; and
waits until Coolify reports it `finished`. Last, it polls `/healthz` over
HTTPS and fails the run if the new version isn't serving.

Coolify does a rolling update: it starts the new container (whose entrypoint
runs `alembic upgrade head`), waits for its health check, then stops the old
one. A failed health check leaves the old version serving.

**Rollback:** deploy an earlier commit's tag, from Coolify (change the tag,
Deploy) or from a laptop:

```sh
COOLIFY_URL=… COOLIFY_TOKEN=… COOLIFY_APP_UUID=… \
CF_ACCESS_CLIENT_ID=… CF_ACCESS_CLIENT_SECRET=… scripts/coolify-deploy.sh <commit sha>
```

That rolls back code, not schema: migrations are not downgraded. Keep
migrations additive so the previous image still runs against the new schema.

### Operational notes

- **Errors go to Sentry** once `SENTRY_DSN` is set in Coolify's environment
  tab (optionally `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`). The
  release is the commit sha, baked into the image by CI. Failed syncs and
  deliveries show up too, since they are logged as errors. Tokens in URLs are
  redacted before anything is sent.
- **TLS** is Cloudflare's edge plus the tunnel; Traefik in Coolify only sees
  plain http. That is what makes `IG_REDIRECT_URI` a valid public HTTPS URL.
  Because the Coolify domains are `http://`, a Terraform-managed redirect rule
  sends plain-http visitors of the app and dashboard to `https`, so Basic auth
  never travels in cleartext. It is per hostname: the zone also hosts other
  sites.
- **Request timeouts:** Traefik v3 cuts off reading a request body after 60s
  by default. If a large video upload from a slow phone connection fails,
  raise `entryPoints.http.transport.respondingTimeouts.readTimeout` in
  *Servers → Proxy* (it is `http`, not `https`, because TLS no longer ends at
  Traefik).
- **Cloudflare's free plan rejects request bodies over 100 MB**, so a very
  large video upload in the compose wizard fails at the edge, whatever the app
  allows.
- **Bot Fight Mode must stay off** for this zone: it cannot be skipped on the
  free plan, and it blocks Meta's image fetcher. A Terraform rule skips the
  other bot checks for `/media/` and `/healthz`. Verify with the "prove a
  tunnel is good enough for Meta" check in
  [`docs/development.md`](docs/development.md) after changing Cloudflare
  settings.
- **The Proxmox UI is never on the tunnel.** Only the app and the Coolify
  dashboard are.
- **Uptime follows home power and internet.** While the box is down the app is
  unreachable; the poller catches up afterwards.
- **Cloud-init runs once.** Editing `infra/cloud-init/` later does nothing to
  the running VM (`ignore_changes` on the VM), and `prevent_destroy` stops
  Terraform from deleting the machine that holds the database. Change a
  running VM by hand; rebuilding is a deliberate edit of those lifecycle
  lines.
- **Postgres is never public.** The app reaches it over Coolify's internal
  Docker network; leave "Make it publicly available" off.
- **Post images live in Postgres.** Instagram's CDN links expire, so each sync
  stores a copy of every still image in the `previews` table while the link is
  fresh, and the UI serves them from `/posts/<id>/media/<n>`. A few hundred KB
  per image; it grows with the number of posts, not with time. The app
  container itself holds no state and needs no volume.
- **No backups**, on purpose. Losing the VM loses the posts, drafts, review
  log and tokens; Instagram has to be reconnected after a rebuild. Coolify's
  database Backups tab is the place to start if that changes.
- **`--workers 1` is still load-bearing.** The poller runs inside the app
  process, so a second worker means two pollers racing. The brief overlap
  during a rolling update is harmless, because an interval job first fires one
  interval after the process starts.
