# CLAUDE.md

The digital backbone of the diffus.space association: one FastAPI app, built up one
bounded context at a time. **This is phase one.** Two contexts exist so far —
`crossposting` (a source's posts fanned out to sinks, behind an approval queue called
"Freigabe") and `calendar` (a shared external calendar, linked to posts). More sources
and sinks, then unrelated domains (members, onboarding, …) follow as further contexts.
German UI. Docs: `readme.md` (what it does today), `docs/architecture.md` (decisions,
domain model, layout, sharp edges), `docs/development.md` (how to run it).

## Never commit

Do not `git commit`, `git push`, tag, stash, or otherwise change git history or the
remote. Leave changes in the working tree; the owner reviews and commits.

## Domain-driven design

The code is DDD with bounded contexts. Keep it that way — no shortcuts across
layers, even for small changes.

**Layers, per context** (`src/diffus/<context>/`):

| Layer | Holds | May import |
|---|---|---|
| `domain/` | entities, value objects, ports (`Protocol`s), errors | stdlib only |
| `application/` | use cases, one class per command or query | `domain/` (plus `shared/dates.py`) |
| `infrastructure/` | adapters: SQLAlchemy models, repositories, unit of work, HTTP clients, sinks | domain, application, shared |
| `presentation/` | typed `Services`, routes, Jinja templates | application, shared |

- Business rules live on entities (`Delivery.can_retry()`, `PostDraft.submit_for_review()`,
  `Token.can_publish`), never in SQL, routes or adapters. A state transition raises
  `ValueError` from any status it does not allow.
- Use cases depend on ports. `src/diffus/app.py` is the only composition root and
  the only place adapters are constructed and wired together.
- Adapters receive plain values (a `Token`, a path), never repositories or `Settings`.

**Bounded contexts** (`crossposting/` and `calendar/` today; every later domain is a new
context, not more entities in an existing one):

- Contexts never import each other from `domain/`, `application/` or `presentation/`.
  To read from or command another context: add a port to your own `domain/` and an
  adapter in your own `infrastructure/`. That adapter may call the other context's
  `application/` use cases — its public API — and translate what they return into
  your own domain's types. Nothing deeper.
- A context's tables never foreign-key another context's tables.
- Context-neutral code (settings, DB `Base`, session, HTTP Basic auth, base template,
  scheduler bootstrap) lives in `src/diffus/shared/`. Nothing context-specific goes there.
- A new context is a sibling package with the same four layers, its own `UnitOfWork`
  and its own `Services`, mounted under its own router prefix. One FastAPI app, one
  Alembic history.

**Unit of work:**

- A use case opens `async with self.uow() as uow:` per persistence boundary. Writes
  call `uow.commit()` explicitly; reads never commit; repositories never commit.
- A unit of work never spans a network call: load what you need, leave the block,
  call the source or sink, open a new block to record the result.

**Post ids** are unique across sources: every new source emits `"<source>:<external id>"`.
Adding a sink or a source is described under "Conventions" in `docs/architecture.md`
and needs no domain, schema or route change.

When a change touches a decision, an entity, the schema or the layout, update
`docs/architecture.md` in the same change.

## Working in the repo

```sh
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
cd web && npm run check && npm run build   # frontend: Vite + TypeScript + htmx; CI runs both lines
```

- Python 3.14 via `uv`; ruff, line length 100; `ty` for types.
- `uv run prek install` once per clone: every commit then runs `ruff check --fix`,
  `ruff format` and `ty check` through the same `uv run` commands
  (`.pre-commit-config.yaml`). A hook that changes a file stops the commit; re-stage.
- Tests use in-memory fakes — no database, no network — so green tests do not prove
  the SQL. The Postgres-backed suite is gated by `TEST_DATABASE_URL`; see
  `docs/development.md` for running it inside compose.
- Adapter tests (`tests/mocks/`) run the *real* adapter against the mock server in
  `mocks/`. A new external call needs the mock extended and such a test added.
- Alembic migrations (`alembic/`) are one history for all contexts and run on
  container start.
- The frontend is a separate build; `uv run` never touches it. All CSS lives in
  `web/src/styles.css` (one exception: the self-contained offline page
  `web/public/offline.html`); templates reference built files through `asset()`.

**Running the stack has real side effects.** Against the real services, approving in
Freigabe sends to the actual Telegram chat, publishing with Instagram ticked posts
publicly, and "Termin anlegen" writes into the shared calendar. Click through flows
on the mocks stack only:

```sh
docker compose -f docker-compose.yml -f docker-compose.mocks.yml up --build   # nothing leaves the machine
```

The real, mocks and tunnel stacks share one compose project and port 8000, so only
one runs at a time. Do not start the real stack or the tunnel unless asked.
