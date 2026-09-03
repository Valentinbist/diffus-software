"""Use case: keep the stored Instagram token fresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from diffus.crossposting.domain.entities import Token
from diffus.crossposting.domain.ports import AuthGateway, UnitOfWorkFactory


@dataclass
class EnsureFreshToken:
    auth: AuthGateway
    uow: UnitOfWorkFactory

    async def run(self) -> Token | None:
        async with self.uow() as uow:
            token = await uow.tokens.get(self.auth.source)
        if token is None:
            return None
        if not token.needs_refresh(datetime.now(UTC)):
            return token

        refreshed = await self.auth.refresh(token)

        async with self.uow() as uow:
            await uow.tokens.save(refreshed)
            await uow.commit()
        return refreshed
