"""Telegram HTML-parse-mode caption rendering."""

from __future__ import annotations

import html

from connector.domain.entities import Post

MAX_CAPTION_LENGTH = 1024
ELLIPSIS = "…"


def render_caption(post: Post) -> str:
    permalink = html.escape(post.permalink, quote=True)
    suffix = f'\n\n<a href="{permalink}">Instagram ↗</a>'

    caption = html.escape(post.caption or "")
    available = MAX_CAPTION_LENGTH - len(suffix)
    if len(caption) > available:
        keep = max(available - len(ELLIPSIS), 0)
        caption = caption[:keep] + ELLIPSIS

    return caption + suffix
