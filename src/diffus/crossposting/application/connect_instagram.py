"""Use case: OAuth connect flow for the single Instagram account."""

from __future__ import annotations

from dataclasses import dataclass

from diffus.crossposting.domain.entities import Token
from diffus.crossposting.domain.ports import AuthGateway, UnitOfWorkFactory


@dataclass
class ConnectInstagram:
    auth: AuthGateway
    uow: UnitOfWorkFactory

    def authorize_url(self) -> str:
        return self.auth.authorize_url()

    async def complete(self, code: str) -> Token:
        token = await self.auth.exchange_code(code)
        async with self.uow() as uow:
            await uow.tokens.save(token)
            await uow.commit()
        return token
