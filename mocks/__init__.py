"""Local mocks of diffus's three external APIs (Instagram, kalender.digital, Telegram).

Lives outside `src/diffus` on purpose: nothing under `src/` imports this
package, and the `runtime` Docker image never ships it — see `mocks/app.py`
and `docker-compose.mocks.yml`. `tests/mocks/` runs the real adapters
against these mocks so the two can't silently drift apart.
"""

from __future__ import annotations
