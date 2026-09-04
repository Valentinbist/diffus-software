"""`python -m mocks` — an alias for `uv run uvicorn mocks.app:app --port 8100 --reload`."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("mocks.app:app", host="0.0.0.0", port=8100, reload=True)
