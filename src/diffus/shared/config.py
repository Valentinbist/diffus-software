"""Application settings, loaded from environment / .env.

Kept outside the domain/application/infrastructure layering on purpose: it is
pure configuration, read by the composition root (presentation/app.py) and by
alembic/env.py. Nothing in domain or application imports this module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def is_public_https(base_url: str, allow_http: bool = False) -> bool:
    """Whether `base_url` is fit for Instagram to fetch a draft's images from.

    `https://` always qualifies; `http://` only when `allow_http` is set —
    dev/mocks only (see `Settings.publish_allow_http`). Instagram itself
    would never accept an `http://` URL; this rule only ever loosens what
    *this app* is willing to try, e.g. against the local Instagram mock.
    The one shared rule `PublishDraft` and `GetChannels` both apply, so the
    two can't drift.
    """
    return base_url.startswith("https://") or (allow_http and base_url.startswith("http://"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    ig_app_id: str
    ig_app_secret: str
    ig_redirect_uri: str
    telegram_bot_token: str
    telegram_chat_ids: str
    poll_interval_minutes: int = 5
    basic_auth_username: str
    basic_auth_password: str
    # IANA zone for the times the UI shows; storage stays UTC.
    display_timezone: str = "Europe/Berlin"

    # Instagram host overrides — real defaults, so production and every
    # existing test are untouched. Only ever changed to point at the local
    # Instagram mock (see mocks/instagram.py and docker-compose.mocks.yml).
    instagram_graph_base: str = "https://graph.instagram.com"
    instagram_api_base: str = "https://api.instagram.com"
    instagram_authorize_url: str = "https://www.instagram.com/oauth/authorize"
    # Telegram Bot API host override, same idea (see mocks/telegram.py).
    telegram_api_base: str = "https://api.telegram.org"
    # Dev-only escape hatch: lets an http:// PUBLIC_BASE_URL count as
    # publishable, so Instagram-publish can be exercised against the local
    # mock without a tunnel. Instagram itself would never accept an
    # http:// image URL — this only ever affects what *this app* is willing
    # to try, never what the real Instagram API does. Never set in production.
    publish_allow_http: bool = False

    # kalender.digital share-link token (the "capabilityId"); empty = calendar
    # sync disabled.
    kalender_digital_token: str = ""
    kalender_digital_api_base: str = "https://api.kalender.digital"
    # How far the calendar sync reaches back and ahead, in whole months.
    calendar_past_months: int = 3
    calendar_future_months: int = 6

    # Where this app itself is publicly reachable, so Instagram can fetch a
    # draft's images from `/media/drafts/...`. Empty disables nothing by
    # itself, but PublishDraft refuses an Instagram target unless this is a
    # public https URL — see public_https below.
    public_base_url: str = ""

    @property
    def chat_ids(self) -> list[str]:
        return [c.strip() for c in self.telegram_chat_ids.split(",") if c.strip()]

    @property
    def calendar_enabled(self) -> bool:
        return bool(self.kalender_digital_token)

    @property
    def public_https(self) -> bool:
        return is_public_https(self.public_base_url, self.publish_allow_http)


@lru_cache
def get_settings() -> Settings:
    return Settings()
