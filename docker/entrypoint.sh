#!/bin/sh
# Apply pending migrations, then hand PID 1 to the server so it gets SIGTERM.
# Both stages put /app/.venv/bin on PATH, so `alembic` and `uvicorn` resolve
# without uv. Runs from /app, where alembic.ini expects to be.
set -eu
alembic upgrade head
exec "$@"
