"""Placeholder media the mocks serve in place of real CDN files.

Real Instagram/Telegram media is a photo or video the association actually
posted; the mocks have neither, so every "image" they hand back is a
generated placeholder — a solid colour (deterministic per label, so the same
post always looks the same) with the label drawn across it, which is enough
for a human clicking through the local UI to tell posts and carousel items
apart at a glance.
"""

from __future__ import annotations

import io
import zlib

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1080

# A handful of distinct, readable-with-white-text colours; which one a label
# gets is deterministic (crc32, not the randomised built-in hash()) so a
# reseed or a second process draws the same post in the same colour.
_PALETTE = [
    (216, 27, 96),
    (30, 136, 229),
    (0, 137, 123),
    (251, 140, 0),
    (94, 53, 177),
    (67, 160, 71),
    (229, 57, 53),
    (0, 121, 107),
]


def _color_for(label: str) -> tuple[int, int, int]:
    return _PALETTE[zlib.crc32(label.encode()) % len(_PALETTE)]


def placeholder_jpeg(label: str, *, size: tuple[int, int] = (WIDTH, HEIGHT)) -> bytes:
    """A solid-colour JPEG with `label` drawn across it, deterministic per label."""
    image = Image.new("RGB", size, _color_for(label))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(size[0] // 12, 12))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size[0] - text_w) / 2 - bbox[0], (size[1] - text_h) / 2 - bbox[1]),
        label,
        fill=(255, 255, 255),
        font=font,
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def placeholder_video_bytes(label: str) -> bytes:
    """A tiny non-JPEG blob served with a video/mp4 content type.

    Nothing decodes this as a real video — the app only ever downloads a
    video for its still `thumbnail_url` (see MediaItem.preview_url); the
    `media_url` bytes themselves are never opened as an image, so a real MP4
    encoder would be wasted effort here.
    """
    return f"MOCK-MP4:{label}".encode()
