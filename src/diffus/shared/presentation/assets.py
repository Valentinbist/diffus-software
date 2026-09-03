"""Resolves the frontend build's manifest into the URLs base.html links.

`web/` builds with Vite into this package's static/dist, writing a manifest
(`dist/.vite/manifest.json`, falling back to the older `dist/manifest.json`
path some Vite versions used) that maps `src/main.ts` to its hashed JS file
and CSS bundle. A fresh checkout or a test run without `npm run build` still
needs the app to boot, so a missing manifest logs one warning and falls back
to the unhashed dev filenames instead of raising.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ENTRY = "src/main.ts"
_FALLBACK_JS = "/static/dist/main.js"
_FALLBACK_CSS = "/static/dist/styles.css"


@dataclass(frozen=True, slots=True)
class Assets:
    js: str
    css: str


def _manifest_path(static_dir: Path) -> Path:
    new_style = static_dir / "dist" / ".vite" / "manifest.json"
    if new_style.exists():
        return new_style
    return static_dir / "dist" / "manifest.json"


def load_assets(static_dir: Path | None = None) -> Assets:
    """The built `<script>`/`<link>` URLs for `src/main.ts`, or a logged-once fallback."""
    if static_dir is None:
        static_dir = Path(__file__).parent / "static"

    manifest_path = _manifest_path(static_dir)
    if not manifest_path.exists():
        logger.warning(
            "no asset manifest at %s; run `npm run build` in web/", manifest_path
        )
        return Assets(js=_FALLBACK_JS, css=_FALLBACK_CSS)

    manifest = json.loads(manifest_path.read_text())
    entry = manifest[_ENTRY]
    css = entry.get("css") or []
    return Assets(
        js=f"/static/dist/{entry['file']}",
        css=f"/static/dist/{css[0]}" if css else _FALLBACK_CSS,
    )
