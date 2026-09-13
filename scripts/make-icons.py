"""Composes the installable app's icons from the diffus.space logo into web/public/icons/.

    uv run python scripts/make-icons.py

The source is web/brand/logo-white.png — the association's mark, white on
transparent, as diffus.space itself serves it (wp-content/uploads/2025/12/
Diffus_Logo_weiss_25_small.png, the same file the site uses as its own
favicon). Each icon is that mark on the page black; how much of the square it
spans depends on who shows it: launchers crop a maskable icon to any shape but
promise to keep the inner 80 %, so that one holds the mark smaller. The PNGs
are checked in — the Docker `web` stage is node-only, and Vite copies public/
into dist/ as it is. Rerun after swapping the source.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BLACK = (2, 2, 2, 255)  # --diffus-black
WEB = Path(__file__).resolve().parent.parent / "web"
SOURCE = WEB / "brand" / "logo-white.png"
OUT = WEB / "public" / "icons"

# (file, size, how much of the square the mark spans)
ICONS = [
    ("favicon.png", 64, 1.0),
    ("icon-192.png", 192, 0.84),
    ("icon-512.png", 512, 0.84),
    ("apple-touch-icon.png", 180, 0.84),
    ("icon-maskable-512.png", 512, 0.7),
]


def icon(mark: Image.Image, size: int, span: float) -> Image.Image:
    """The mark, centred on a black `size` px square, scaled to `span` of its side."""
    scale = size * span / max(mark.size)
    fitted = mark.resize(
        (round(mark.width * scale), round(mark.height * scale)), Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGBA", (size, size), BLACK)
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas.convert("RGB")


def main() -> None:
    mark = Image.open(SOURCE).convert("RGBA")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, span in ICONS:
        icon(mark, size, span).save(OUT / name, optimize=True)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
