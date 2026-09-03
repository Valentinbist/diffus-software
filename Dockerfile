# syntax=docker/dockerfile:1
#
# Stages (build with --target):
#   base     python + unprivileged `app` user, nothing else
#   deps     third-party packages only; cached until pyproject.toml/uv.lock change
#   builder  deps + the project installed as a real (non-editable) wheel
#   dev      deps + dev tools, project editable, uvicorn --reload  -> docker-compose.yml
#   runtime  what ships: base + the venv from builder, no uv, no sources  -> CI / GHCR
#
# Bump the two pins together with .tool-versions / .python-version.

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

FROM python:3.14-slim-trixie AS base
# Match the host user on Linux so bind mounts in dev are writable; harmless elsewhere.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid "${GID}" app \
 && useradd --uid "${UID}" --gid app --create-home --shell /usr/sbin/nologin app \
 && install -d -o app -g app /app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH


FROM base AS deps
COPY --from=uv /uv /usr/local/bin/uv
# never: the venv must use this image's /usr/local/bin/python3.14, which the
# runtime stage shares, not a uv-managed interpreter that it would not have.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


FROM deps AS builder
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM deps AS dev
# Dev tools before the sources, so editing code never reinstalls pytest/ruff/ty.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project
COPY src ./src
COPY tests ./tests
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
# Editable install: the package resolves to /app/src, which docker-compose.yml
# bind-mounts from the host so uvicorn --reload picks up edits.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen
# Don't litter the bind-mounted host tree with __pycache__.
ENV PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8000
ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "diffus.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/src", "--reload-include", "*.html"]


FROM base AS runtime
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
USER app
EXPOSE 8000
ENTRYPOINT ["entrypoint"]
# --workers 1 is load-bearing: the Instagram poller runs inside this process
# (FastAPI lifespan task). More workers = racing pollers. See docs/architecture.md.
CMD ["uvicorn", "diffus.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
