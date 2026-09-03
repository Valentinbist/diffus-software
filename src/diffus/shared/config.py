"""Application settings, loaded from environment / .env.

Kept outside the domain/application/infrastructure layering on purpose: it is
pure configuration, read by the composition root (presentation/app.py) and by
alembic/env.py. Nothing in domain or application imports this module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # kalender.digital share-link token (the "capabilityId"); empty = calendar
    # sync disabled.
    kalender_digital_token: str = ""
    kalender_digital_api_base: str = "https://api.kalender.digital"
    # How far the calendar sync reaches back and ahead, in whole months.
    calendar_past_months: int = 3
    calendar_future_months: int = 6

    @property
    def chat_ids(self) -> list[str]:
        return [c.strip() for c in self.telegram_chat_ids.split(",") if c.strip()]

    @property
    def calendar_enabled(self) -> bool:
        return bool(self.kalender_digital_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()
