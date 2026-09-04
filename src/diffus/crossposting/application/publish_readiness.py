"""Use case: what the UI needs to know before offering "publish to Instagram"."""

from __future__ import annotations

from dataclasses import dataclass

from diffus.crossposting.domain.ports import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class PublishReadiness:
    connected: bool
    can_publish: bool
    public_https: bool


@dataclass
class GetPublishReadiness:
    uow: UnitOfWorkFactory
    source: str
    public_base_url: str

    async def run(self) -> PublishReadiness:
        async with self.uow() as uow:
            token = await uow.tokens.get(self.source)
        return PublishReadiness(
            connected=token is not None,
            can_publish=token is not None and token.can_publish,
            public_https=self.public_base_url.startswith("https://"),
        )
