"""load_assets: resolves web/'s Vite manifest into the URLs base.html links."""

from __future__ import annotations

import json
import logging

from diffus.shared.presentation.assets import Assets, load_assets


def write_manifest(tmp_path, path: str, content: dict) -> None:
    manifest_path = tmp_path / path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(content))


def test_load_assets_resolves_the_entrys_hashed_js_and_css_from_the_manifest(tmp_path):
    write_manifest(
        tmp_path,
        "dist/.vite/manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main-abc123.js",
                "src": "src/main.ts",
                "isEntry": True,
                "css": ["assets/main-def456.css"],
            }
        },
    )

    assets = load_assets(tmp_path)

    assert assets == Assets(
        js="/static/dist/assets/main-abc123.js", css="/static/dist/assets/main-def456.css"
    )


def test_load_assets_falls_back_to_the_older_manifest_path(tmp_path):
    write_manifest(
        tmp_path,
        "dist/manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main-xyz.js",
                "src": "src/main.ts",
                "isEntry": True,
                "css": ["assets/main-xyz.css"],
            }
        },
    )

    assets = load_assets(tmp_path)

    assert assets.js == "/static/dist/assets/main-xyz.js"
    assert assets.css == "/static/dist/assets/main-xyz.css"


def test_load_assets_without_a_manifest_logs_once_and_falls_back(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assets = load_assets(tmp_path)

    assert assets == Assets(js="/static/dist/main.js", css="/static/dist/styles.css")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "npm run build" in warnings[0].getMessage()
