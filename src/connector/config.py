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

    @property
    def chat_ids(self) -> list[str]:
        return [c.strip() for c in self.telegram_chat_ids.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
