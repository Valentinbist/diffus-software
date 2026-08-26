"""Use case: OAuth connect flow for the single Instagram account."""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.entities import Token
from connector.domain.ports import AuthGateway, TokenRepository


@dataclass
class ConnectInstagram:
    auth: AuthGateway
    tokens: TokenRepository

    def authorize_url(self) -> str:
        return self.auth.authorize_url()

    async def complete(self, code: str) -> Token:
        token = await self.auth.exchange_code(code)
        await self.tokens.save(token)
        return token
