"""Typed home for everything a route needs from the composition root.

Replaces the untyped `request.app.state` bag: one frozen dataclass, built
once by the composition root (presentation/app.py) — or directly from fakes
in tests — and handed to routes through the `get_services` dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Request
from fastapi.templating import Jinja2Templates

from diffus.crossposting.application.connect_instagram import ConnectInstagram
from diffus.crossposting.application.overview import GetOverview
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.application.preview import GetPreview
from diffus.crossposting.application.resend_delivery import ResendDelivery
from diffus.crossposting.application.sync_job import SyncJob
from diffus.crossposting.domain.entities import Destination


@dataclass(frozen=True, slots=True)
class Services:
    sync_job: SyncJob
    connect: ConnectInstagram
    resend: ResendDelivery
    overview: GetOverview
    detail: GetPostDetail
    preview: GetPreview
    destinations: Sequence[Destination]
    templates: Jinja2Templates


def get_services(request: Request) -> Services:
    return request.app.state.services
