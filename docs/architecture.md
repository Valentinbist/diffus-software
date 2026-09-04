# Architecture

The connector is the first bounded context of the association's digital
backbone: **crossposting** — poll a source, fan out each new post to a set of
destinations, and show what happened. Instagram → Telegram is the only pairing
wired today; the model no longer assumes it.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| IG access | **Business Login for Instagram** (`graph.instagram.com`, scopes `instagram_business_basic,instagram_business_content_publish` — the second scope is what lets the compose wizard publish; changing the scope string forces a one-time re-connect) | Own accounts, no Facebook Page dependency. Basic Display API is dead. |
| Tokens | Long-lived (60d); `Token.needs_refresh()` says refresh after **50 days** or within 7 of expiry | #1 cause of silent death. Refresh rides the sync cadence (see sharp edges). |
| New posts | **Poll** `GET /{ig-user-id}/media` | IG webhooks are unreliable for new media |
| Storage | **Postgres** (SQLAlchemy 2.0 async + Alembic + asyncpg) | Already running compose. Backup = `pg_dump` cron. |
| Exactly-once | one `deliveries` row per `(post_id, sink, address)`, PK-enforced; claimed with `INSERT … ON CONFLICT DO NOTHING … RETURNING` | The core invariant; retry-safe by construction |
| Retries | `Delivery` owns it: a FAILED row is retried on every poll until `Delivery.MAX_ATTEMPTS` (5); manual resend bypasses the cap | Policy lives on the entity, so SQL and the test fakes can't drift |
| Approval (Freigabe) | Per-channel `channel_settings.auto_publish`, default **off**; a fresh delivery or a submitted draft queues in `REVIEW` unless every channel it targets is already switched on | Owner wants "Freigabe first": nothing goes out unreviewed until a channel is explicitly opted in |
| Persistence boundary | **Unit of Work** (`UnitOfWork` port, `SqlUnitOfWork`); repositories are bound to its session and never commit | Use cases own their transaction boundaries; one place to hook domain events later |
| Topology | **One process**: poller as an APScheduler job in the FastAPI `lifespan`, `uvicorn --workers 1` (pinned) | One sink doesn't need workers |
| Queue/broker | None | Postgres is enough at this scale |
| Media | Download to tempfile → hand `MediaFile(item, path)` to the sink → delete | IG CDN URLs are short-lived; a file path is the one payload every sink can use |
| Routing | `TELEGRAM_CHAT_IDS` env var → `Destination("telegram", chat_id)` list built in the composition root | Edited twice a year, no CRUD needed |
| UI | Jinja served by FastAPI, German, matching the diffus.space design system, plus a Vite/TypeScript/htmx build (`web/`) for progressive-enhancement client code; on a ≥ 900 px viewport, detail pages (a post, an event, a wizard) open as a `<dialog>` modal instead of a full navigation | Every URL still works as a full page (phones, no-JS, crawlers); the modal is additive, not a second UI |
| Auth | `HTTPBasic` + `secrets.compare_digest`, creds from env | Needs TLS in front (Caddy) — required anyway for the OAuth redirect URI |

## Domain model

```text
Post          id, source, caption, permalink, media, posted_at
Destination   (sink, address)  value object; text form "telegram:-100…"
Delivery      post_id, destination, status, attempts, sent_at, error
              can_retry() / record_sent() / record_failure() / skip()
              # Freigabe: queue_for_review() / approve() / reject() — PENDING -> REVIEW ->
              # {PENDING, SKIPPED}, each raising ValueError from any other status. can_retry()
              # is deliberately unchanged: a REVIEW row is never FAILED, so the poller never
              # retries it — only a human (or the badge reminding them) moves it on.
DeliveryStatus PENDING / REVIEW / SENT / FAILED / SKIPPED
Token         source, access_token: AccessToken, external_user_id, expires_at, refreshed_at, scopes
              needs_refresh(now) / can_publish  # PUBLISH_SCOPE in scopes.split(",")
AccessToken   value object whose repr/str never reveal the secret
Preview       a stored still image per (post_id, media index)
MediaFile     (MediaItem, Path) — what a sink receives
PostDraft     id, caption, public_key, images: DraftImage[], status, error, post_id, created_at, published_at,
              targets: PublishTargets | None, event_ref: str | None  # "calendar:<event id>"
              # a post being composed, between upload and publish — see "Public media route" below
              mark_published(post_id, now) / mark_failed(error) / public_media_url(base, index)
              submit_for_review(targets)  # DRAFT -> REVIEW, storing the chosen targets
              is_reviewable()  # status in {REVIEW, FAILED} and targets is not None — the
                                # Freigabe page offers a queued draft AND a retryable failure
DraftStatus   DRAFT / REVIEW / PUBLISHED / FAILED
DraftImage    content_type, width, height, data  # one already-normalised (JPEG) upload
PublishTargets instagram: bool, destinations: tuple[Destination, ...]  # what the wizard's publish step chose
ChannelPolicy destination: Destination, auto_publish: bool  # one channel_settings row (see Freigabe below)
INSTAGRAM_CHANNEL  Destination("instagram", "account")  # the fixed key for both the Instagram
              # channel_settings row and the SENT Delivery a wizard post records when it publishes
              # to Instagram; fixed rather than keyed by the connected account's id because the
              # switch (and the settings row) must exist before any token does
ComposeHint   event_id, title, caption, detail_url  # what the calendar offers to prefill the
              # compose wizard for one event; a small mirror of calendar.domain.entities.ComposeHint
              # (identical fields on both sides — the hint needs nothing context-specific), read via
              # EventDirectory.compose_hint
LinkedEvent   id, title, starts_at, detail_url, removed
              # the connector's own view of a calendar event, via EventDirectory — mirrors
              # calendar.domain.entities.LinkablePost the other way round
```

Ports (`domain/ports.py`): `PostSource` (has a `source` name, fetches with a
`Token`), `PostSink`, `MediaGateway`, `AuthGateway` (has a `source` name), the
five repositories (`PostRepository`, `DeliveryRepository`, `PreviewRepository`,
`TokenRepository`, `DraftRepository`), `EventDirectory` (read-only window onto
the calendar context's events, keyed by post — `for_posts(post_ids)`),
`ImageProcessor` (`normalise(data) -> DraftImage`, sync/CPU-bound),
`MediaPublisher` (`publish_images(token, image_urls, caption) -> media_id`,
`fetch_post(token, post_id) -> Post` — what publishes a draft to a source and
reads the result back), and `UnitOfWork` / `UnitOfWorkFactory`.

**Post id rule.** `posts.id` is the primary key and must be unique across
sources. Instagram ids stay bare (existing data). Every *new* source adapter
emits `"<source>:<external id>"` as `Post.id`.

### Calendar context

```text
SubCalendar    id, name, color, position                        # one room/category in the shared calendar
CalendarEvent  id, title, description, who, location, starts_at, ends_at, whole_day,
               sub_calendar_ids, series_id, removed_at
               local_days(tz) -> every local calendar day the [starts_at, ends_at) interval touches
               removed
EventLink      event_id, post_id, linked_at                      # many-to-many, event <-> post
LinkablePost   id, caption, permalink, posted_at, thumbnail_url, detail_url, delivered
               # the calendar's own view of a post, via PostCatalog — not crossposting's PostView
NewEvent       title, description, who, location, starts_at, ends_at, whole_day, sub_calendar_ids
               # UTC, exclusive end, like CalendarEvent — but no id yet: the post → event wizard's
               # draft, before CalendarGateway.create_event writes it and reads the real event back
DraftRef       id                                                # a just-created crossposting draft
DraftPreview   id, caption, image_urls: tuple[str, ...]          # what the compose preview shows
TelegramTarget address, label                                    # one selectable Telegram destination
InstagramState READY / NOT_CONNECTED / NO_PUBLISH_SCOPE / NO_PUBLIC_URL
PublishOptions instagram: InstagramState, targets: tuple[TelegramTarget, ...]
PublishedPost  id, permalink, detail_url                         # what publishing a draft returns
```

Ports (`calendar/domain/ports.py`): `CalendarGateway` (fetches a
`CalendarSnapshot` for a date range; `create_event(NewEvent) -> CalendarEvent`
writes a new event and reads it back — network, no unit of work), `PostCatalog`
(`recent`/`by_ids`, the calendar's read-only window onto crossposting's
posts), `PostPublisher` (`options`, `create_draft`, `get_draft`, `publish`,
`discard` — composes and publishes a post via the crossposting context; see
`CrosspostingPublisher` below), the three repositories
(`SubCalendarRepository`, `EventRepository`, `EventLinkRepository`), and
`CalendarUnitOfWork` / `CalendarUnitOfWorkFactory` — its own unit of work,
separate from crossposting's.

## Schema (4 tables, + 2 more in migration `0005`)

```sql
tokens      (source PK, access_token, external_user_id, expires_at, refreshed_at, scopes)
posts       (id PK, source, caption, permalink, media JSONB, posted_at, fetched_at)
previews    (post_id, media_index, content_type, data, fetched_at)  PRIMARY KEY (post_id, media_index)
deliveries  (post_id, sink, address, status, attempts, sent_at, error)
             PRIMARY KEY (post_id, sink, address)
```

No `accounts` table: one connection per source. Multi-account would key
`tokens` (and routing) by an account id; that is a schema change, deliberately
not made yet. `tokens.scopes` (migration `0005`) is a plain comma-joined
string of the OAuth scopes the stored token actually carries; a token
connected before the publish scope existed has `scopes = ""` and needs a
one-time re-connect (`Token.can_publish`).

### Drafts (migration `0005`)

```sql
post_drafts       (id PK, caption, public_key, status, error, post_id, created_at, published_at)
post_draft_media  (draft_id FK post_drafts.id ON DELETE CASCADE, media_index,
                    content_type, width, height, data)  PRIMARY KEY (draft_id, media_index)
```

A wizard that composes a post is two requests apart (upload images, then
choose targets and publish), so the uploaded images — already normalised to
JPEG — and the caption have to survive between them; `post_drafts` is that
storage, `post_draft_media` one row per image. `post_drafts.post_id` carries
no foreign key on purpose: the `posts` row is only created once publishing
succeeds, well after the draft exists, and the draft is kept afterwards as an
audit trail that outlives the row it produced — see Sharp edges, "drafts are
never purged."

### Calendar schema (4 more tables, migration `0004`)

```sql
calendar_sub_calendars       id PK, name, color, position
calendar_events              id PK, title, description, who, location, starts_at, ends_at,
                              whole_day, series_id, fetched_at, removed_at
calendar_event_sub_calendars event_id FK calendar_events.id, sub_calendar_id FK calendar_sub_calendars.id
                              PRIMARY KEY (event_id, sub_calendar_id)
calendar_event_posts         event_id FK calendar_events.id, post_id, linked_at
                              PRIMARY KEY (event_id, post_id)
```

`calendar_event_posts.post_id` has **no foreign key**: `posts` lives in the
crossposting context's schema, and a context's tables never reference another
context's tables directly — the calendar only ever reaches a post through
`PostCatalog`, never a join. Migration `0005` adds
`ix_calendar_event_posts_post_id` (an index on `post_id`, the reverse of the
table's own primary-key order), because `GetLinkedEvents.for_posts` and the
index/post-page "Termine" section now look events up by a list of post ids.

## Layout

```text
web/                              # Vite + TypeScript + htmx (npm dep, not a CDN); builds into
                                   #   src/diffus/shared/presentation/static/dist with a manifest
  package.json, vite.config.ts, tsconfig.json
  src/main.ts                     # htmx config + the ≥ 900px modal wiring (progressive enhancement)
  src/styles.css                  # every rule the templates use; no inline CSS in base.html
src/diffus/
  app.py                         # composition root: lifespan builds the graph, starts the scheduler;
                                  # also defines public_router (/healthz, /media/drafts/...)
  shared/                        # what every bounded context uses; contexts never import each other
    config.py                    # pydantic-settings, env-only; read by the composition root and alembic
    dates.py                     # MONTHS/WEEKDAYS — the one shared/ module calendar/application may import
    db/base.py                   # `Base(DeclarativeBase)`; every context's models inherit from it
    db/session.py                # engine / session factory construction
    scheduler.py                 # start_scheduler(): one AsyncIOScheduler interval job
    presentation/
      auth.py                    # HTTP Basic auth dependency, applied to every route
      display.py                 # German date/time/text formatting; re-exports shared/dates.py
      templates.py                # build_templates(): Jinja2Templates + shared filters + assets global
      assets.py                  # load_assets(): resolves web/'s build manifest into asset() URLs
      templates/base.html         # topbar, <dialog id="modal">, asset() links
      static/dist/                # npm run build's output (gitignored); FastAPI serves it at /static
  crossposting/                  # first bounded context — poll a source, fan out, show what happened
    domain/                      # entities, value objects, ports, errors — stdlib only
    application/                 # use cases; depend only on domain
      sync_posts.py               #   poll → upsert + previews → claim → DeliverPost, per destination
      deliver.py                  #   DeliverPost: sink registry lookup, deliver, record, commit
      sync_job.py                 #   SyncJob: refresh token, then sync, under one lock; LastRun for the UI
      resend_delivery.py, refresh_token.py, connect_instagram.py
      overview.py, post_detail.py, preview.py     # read side
      drafts.py                   #   CreateDraft, GetDraft, DiscardDraft, GetDraftImage
      publish_draft.py            #   PublishDraft: the compose wizard's publish step (see Sharp edges)
      publish_readiness.py        #   GetPublishReadiness: feeds calendar's PublishOptions + the IG hint
      draft_media.py               #   DraftMediaGateway: a draft's own bytes as a MediaGateway for Telegram
    infrastructure/
      db/                         # models (Base from shared), repositories (session-bound), uow.py
      instagram/                  # Graph client: PostSource + AuthGateway + MediaPublisher, source = "instagram"
      telegram/                   # render (HTML captions) + sink (PostSink)
      media/
        downloader.py              #   CDN download to tempdir → MediaFile
        images.py                  #   PillowImageProcessor: ImageProcessor, upload → normalised JPEG
      calendar.py                  #   CalendarEventDirectory: EventDirectory over the calendar's read use cases
    presentation/
      services.py                 # typed Services dataclass handed to routes via Depends
      routes.py, display.py, templates/            # context-specific filters + templates
  calendar/                       # second bounded context — sync a shared external calendar,
                                  #   link events to posts, show what's covered and what isn't
    domain/                      # entities (SubCalendar, CalendarEvent, EventLink, LinkablePost, NewEvent,
                                  #   DraftRef, DraftPreview, TelegramTarget, PublishOptions, PublishedPost),
                                  #   ports (CalendarGateway, PostCatalog, PostPublisher, repositories,
                                  #   UnitOfWork), errors
    application/
      sync_calendar.py, sync_job.py                # SyncCalendar + CalendarSyncJob, mirrors crossposting's
      calendar_events.py, event_detail.py           # read side: agenda/month query, one event's detail
      link_event_post.py, link_picker.py            # link/unlink a post to an event, and the reverse picker
      linked_events.py                              # GetLinkedEvents: crossposting's EventDirectory reads this
      suggest_posts.py, caption_dates.py             # the link-picker's scoring heuristic; pure, stdlib only
      compose_post.py                               # ComposePostForEvent: the event → post wizard
      create_event.py                               # CreateEventForPost: the post → event wizard
    infrastructure/
      db/                          # models (Base from shared), repositories, uow.py — mirrors crossposting's
      kalender_digital.py          # KalenderDigitalClient: CalendarGateway (incl. create_event) over
                                    #   kalender.digital's JSON API
      crossposting.py              # CrosspostingPostCatalog: PostCatalog over crossposting's read use cases;
                                    #   CrosspostingPublisher: PostPublisher over its drafting/publishing commands
    presentation/
      services.py, routes.py, display.py
      templates/                   # calendar.html, event.html, link.html, compose.html, compose_preview.html,
                                    #   new_event.html
alembic/                          # 0001 initial, 0002 previews, 0003 destinations and sources, 0004 calendar,
                                   #   0005 drafts and scopes
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
   other. Exception, decided 2026-09-03, **extended 2026-09-04**: an adapter
   in a context's `infrastructure/` may call another context's
   `application/` use cases — reads *and*, since the compose/publish
   wizard, **commands** too — because the application layer of a context is
   its public API. It now runs both ways:
   `calendar/infrastructure/crossposting.py::CrosspostingPostCatalog` reads
   crossposting's posts, and its `CrosspostingPublisher` drives
   crossposting's `CreateDraft`/`PublishDraft`/`DiscardDraft` *commands*;
   `crossposting/infrastructure/calendar.py::CalendarEventDirectory` reads
   the calendar's linked events the other way round.
4. One FastAPI app, one Alembic history, one `Services` per context mounted
   under its own router prefix.

Mechanical cost of that move, done: every `connector.` import under `src/` and
`tests/` became `diffus.crossposting.` / `diffus.shared.` / `diffus.`;
`pyproject.toml` `[project] name` and a `uv lock`; the `Dockerfile` uvicorn
target; `alembic/env.py` imports; the comment in `alembic.ini`; `readme.md`.
Compose, Ansible and the CI workflow never referenced the package path, so
they were untouched.

### Public media route

`GET /media/drafts/{draft_id}/{index}?key=<public_key>` (on `app.py`'s
`public_router`, next to `/healthz`) is the one route in the whole app that
carries **no** HTTP Basic auth. It has to be: Instagram's `POST /{ig_user_id}/media`
takes an `image_url` it fetches itself — it cannot send a Basic-auth header,
and it cannot reach `http://localhost` either, which is why publishing to
Instagram needs `PUBLIC_BASE_URL` to be a real public https address (see
Sharp edges). Leaving a route open to the internet without auth would
normally expose every draft's images to anyone who finds the URL, so instead
it's **key-guarded**: `PostDraft.public_key` is a 32-byte
`secrets.token_urlsafe` generated once per draft, folded into the URL
(`public_media_url`), and compared with `secrets.compare_digest` in
`GetDraftImage.run` — a wrong or missing key 404s exactly like an unknown
draft would, so the route never confirms a draft's existence to a guesser.
The authenticated twin, `GET /drafts/{draft_id}/media/{index}` on the
crossposting router, is what the compose wizard's own preview page uses
instead, behind the normal Basic auth.

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
- Calendar: `KalenderDigitalClient` talks to an **undocumented JSON API**
  (kalender.digital's own Angular frontend uses it); it's pinned by recorded
  payloads in tests, and the documented ICS export shares the same event ids
  so a fallback adapter is a drop-in behind `CalendarGateway` if it ever
  breaks. The share-link token is an **editor-level capability** — anyone
  holding it can edit or delete the whole calendar — passed as a query
  param, so it appears in httpx error strings; `redact()` strips it before
  any error reaches the UI, and the adapter never logs request URLs.
  **Recurring occurrences carry their own stable id**; editing a series
  upstream can re-id its occurrences, so the old ids get `removed_at` (and
  keep their post links, visible via the "gelöscht" notice) while the new
  ids come back unlinked. `series_id` is stored for a later fix that carries
  links across a re-id. `KalenderDigitalClient.create_event` (the post →
  event wizard) writes through the same undocumented API — its shape was
  read from kalender.digital's own bundle, not from any spec, so a write
  failure surfaces as a German error on the form and nothing is written
  locally.
- Instagram publishing (the event → post wizard): **100 API posts per 24 h**
  (`GET /{ig_user_id}/content_publishing_limit`, not yet enforced client-side
  — Meta's own 4xx is what the wizard shows if it's hit); Instagram only
  accepts **JPEG**, which is why every upload is normalised through
  `PillowImageProcessor` regardless of what was uploaded; a media container
  **expires after 24 h**, so a draft left unpublished that long has to be
  re-created; `PUBLIC_BASE_URL` **must be a public https URL** (Instagram
  fetches the image itself and cannot reach `http://localhost`), which makes
  Instagram publishing verifiable only in production or through a public
  tunnel (`cloudflared tunnel --url http://localhost:8000`) — Telegram-only
  publishing works locally without it; a token connected before the publish
  scope existed needs **one re-connect** (`Token.can_publish` is false until
  then, and the compose form disables the Instagram checkbox with a German
  hint instead of failing at publish time).
- `PublishDraft` runs under `SyncJob.lock` — the same lock the crossposting
  poller takes for its own tick — so the poller can never run between
  Instagram's `media_publish` call and this use case's own `posts.upsert` +
  delivery rows; see `publish_draft.py`'s module docstring for the full
  three-plus-one argument against a duplicate Telegram send.
- **Drafts are never purged.** `post_drafts`/`post_draft_media` keep growing;
  a published draft is kept as the audit trail of what was uploaded and
  when, and a discarded/failed one is kept too unless a human calls
  `DiscardDraft` on it. There's no retention job yet.
- A **manual resend of a `diffus:` post** (a Telegram-only post the compose
  wizard created — no Instagram id to key it on) serves its images from
  `DraftMediaGateway`, i.e. the draft's own stored bytes, not a re-download:
  the draft is what makes that resend possible at all once Instagram was
  never involved.
