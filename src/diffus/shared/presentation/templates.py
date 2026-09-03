"""Shared Jinja2Templates construction: filters every bounded context's UI needs."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from diffus.shared.presentation import display


def build_templates(
    tz: ZoneInfo, directories: Sequence[Path], globals: Mapping[str, object] = {}
) -> Jinja2Templates:
    """Jinja2Templates over `directories` (context templates first, shared last) with the
    shared filters installed."""
    templates = Jinja2Templates(directory=[str(d) for d in directories])
    templates.env.filters["when"] = lambda dt, now: display.format_when(dt, now, tz)
    templates.env.filters["day"] = lambda dt, now: display.format_day(dt, now, tz)
    templates.env.filters["ago"] = display.format_ago
    templates.env.filters["summary"] = display.summary
    templates.env.filters["error_text"] = display.error_text
    # Environment.globals' inferred value type is narrower than `object` (it's seeded
    # from jinja2's untyped DEFAULT_NAMESPACE); widen it so arbitrary globals fit.
    env_globals = cast("MutableMapping[str, object]", templates.env.globals)
    env_globals.update(globals)
    return templates
