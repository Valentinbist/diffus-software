"""Use case: keep the stored Instagram token fresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from connector.domain.entities import Token
from connector.domain.ports import AuthGateway, TokenRepository

REFRESH_AFTER_DAYS = 50
REFRESH_WITHIN_EXPIRY_DAYS = 7


@dataclass
class EnsureFreshToken:
    auth: AuthGateway
    tokens: TokenRepository

    async def run(self) -> Token | None:
        token = await self.tokens.get()
        if token is None:
            return None

        now = datetime.now(timezone.utc)
        needs_refresh = (
            now - token.refreshed_at >= timedelta(days=REFRESH_AFTER_DAYS)
            or token.expires_at - now <= timedelta(days=REFRESH_WITHIN_EXPIRY_DAYS)
        )
        if not needs_refresh:
            return token

        refreshed = await self.auth.refresh(token)
        await self.tokens.save(refreshed)
        return refreshed
