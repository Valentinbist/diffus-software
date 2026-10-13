"""Error reporting to Sentry — off unless SENTRY_DSN is set.

What gets reported: unhandled request errors (FastAPI integration) and every
`logger.exception`/`logger.error` line (logging integration) — the scheduler's
jobs catch their own failures and log them, so that is how a failed sync or
delivery reaches Sentry.

Secrets: the adapters' credentials ride in request URLs (see redact.py), and
httpx quotes those URLs in exception messages and breadcrumbs. Every event,
transaction and breadcrumb is therefore run through `redact` before it leaves
the process, and stack frames carry no local variables, since a frame's `self`
or `url` can hold a token under a name Sentry's own scrubber doesn't know.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk

from diffus.shared.config import SentrySettings
from diffus.shared.redact import redact


def scrub(value: Any) -> Any:
    """`redact` applied to every string inside a (nested) event payload."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    return value


def _before_send(event: Any, hint: Any) -> Any:
    return scrub(event)


def _before_send_transaction(event: Any, hint: Any) -> Any:
    if event.get("transaction") == "/healthz":
        return None
    return scrub(event)


def _before_breadcrumb(crumb: Any, hint: Any) -> Any:
    return scrub(crumb)


def init_sentry(settings: SentrySettings) -> bool:
    """Start the SDK if a DSN is configured; returns whether it did."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
        before_breadcrumb=_before_breadcrumb,
    )
    return True
