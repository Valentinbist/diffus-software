FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer — cached until pyproject/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

# --workers 1 is load-bearing: the Instagram poller runs inside this process
# (FastAPI lifespan task). More workers = racing pollers. See docs/architecture.md.
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev uvicorn connector.presentation.app:app --host 0.0.0.0 --port 8000 --workers 1"]
