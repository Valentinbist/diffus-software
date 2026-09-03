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

from connector.application.connect_instagram import ConnectInstagram
from connector.application.overview import GetOverview
from connector.application.post_detail import GetPostDetail
from connector.application.preview import GetPreview
from connector.application.resend_delivery import ResendDelivery
from connector.application.sync_job import SyncJob
from connector.domain.entities import Destination


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
