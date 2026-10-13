"""shared/sentry.py: nothing secret leaves the process, and no DSN means no SDK."""

from __future__ import annotations

from diffus.shared.config import SentrySettings
from diffus.shared.sentry import _before_send_transaction, init_sentry, scrub


def test_scrub_redacts_secrets_anywhere_in_the_event():
    event = {
        "exception": {
            "values": [
                {
                    "value": "Client error for url 'https://api.telegram.org/bot123:ABC-def/sendPhoto'"
                }
            ]
        },
        "breadcrumbs": {
            "values": [
                {"data": {"url": "https://graph.instagram.com/me?access_token=IGQ123&fields=id"}},
                {"message": "GET https://api.kalender.digital/x?capabilityId=deadbeef"},
            ]
        },
        "level": "error",
        "count": 3,
    }

    scrubbed = scrub(event)

    text = repr(scrubbed)
    assert "ABC-def" not in text
    assert "IGQ123" not in text
    assert "deadbeef" not in text
    assert scrubbed["breadcrumbs"]["values"][0]["data"]["url"].endswith("access_token=…&fields=id")
    assert scrubbed["level"] == "error"
    assert scrubbed["count"] == 3


def test_health_probes_are_not_reported_as_transactions():
    assert _before_send_transaction({"transaction": "/healthz"}, {}) is None
    assert _before_send_transaction({"transaction": "/freigabe"}, {}) is not None


def test_no_dsn_means_sentry_stays_off():
    assert init_sentry(SentrySettings(sentry_dsn="")) is False
