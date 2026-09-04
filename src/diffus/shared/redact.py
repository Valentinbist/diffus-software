"""Strip secrets out of text that might end up on a page or in a log line.

Several adapters talk to APIs that carry a long-lived credential in the
request URL itself rather than a header: the Instagram Graph token
(`access_token=…`), a Telegram bot token embedded in the request path
(`/bot<token>/…`), an OAuth `client_secret`, and kalender.digital's
editor-level share-link token (`capabilityId=…`, see
`calendar/infrastructure/kalender_digital.py`). When a request like that
fails, `httpx` (and anything downstream that formats the exception) quotes
the offending URL verbatim, so the secret rides along into error strings —
and from there into rendered error text or log output — unless something
strips it first. `redact` is that something: every caller that turns an
exception into user-facing or logged text runs it through here first.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"(access_token=)[^&\s'\"]+"),
    re.compile(r"(client_secret=)[^&\s'\"]+"),
    re.compile(r"(/bot)\d+:[\w-]+"),
    re.compile(r"(capabilityId=)[^&\s'\"]+"),
)


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1…", text)
    return text
