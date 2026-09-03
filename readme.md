# Instagram → Telegram connector

Polls one Instagram Business account and fans out new posts to N Telegram chats.
Single Python process (FastAPI + APScheduler), Postgres for state, HTTP Basic
auth on every route. Instagram → Telegram is the only pairing wired today; the
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
2. `docker compose up --build` (the dev stack: hot-reloading app + Postgres;
   the image that ships is the `runtime` stage of the same Dockerfile)
3. Open `http://localhost:8000` (behind Basic auth) and click **Instagram
   verbinden** to complete the OAuth flow. The UI is in German, like the
   diffus.space site it belongs to.

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

Or entirely in Docker. `docker-compose.yml` builds the `dev` stage and
bind-mounts `src/`, so edits reload without a rebuild:

```sh
docker compose up --watch          # also rebuilds on pyproject.toml/uv.lock, restarts on new migrations
docker compose exec app pytest -q  # tests inside the container
```

The `Dockerfile` is staged: `deps` → `builder` → `runtime` (what CI pushes to
GHCR: no uv, no sources, runs as the unprivileged `app` user) and `deps` → `dev`
(dev tools + editable install + `--reload`). The `app` user is uid/gid 1000;
pass `--build-arg UID=$(id -u) --build-arg GID=$(id -g)` on Linux if yours
differs, so the bind mounts stay writable.

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
| `BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD` | UI credentials |

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
