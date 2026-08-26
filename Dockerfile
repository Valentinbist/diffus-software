FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

# --workers 1 is load-bearing: the Instagram poller runs inside this process
# (FastAPI lifespan task). More workers = racing pollers. See docs/architecture-proposals.md.
CMD ["sh", "-c", "alembic upgrade head && uvicorn connector.presentation.app:app --host 0.0.0.0 --port 8000 --workers 1"]
