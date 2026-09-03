"""Use case: fetch one post's stored still image, for the media route."""

from __future__ import annotations

from dataclasses import dataclass

from diffus.crossposting.domain.entities import Preview
from diffus.crossposting.domain.ports import UnitOfWorkFactory


@dataclass
class GetPreview:
    uow: UnitOfWorkFactory

    async def run(self, post_id: str, index: int) -> Preview | None:
        async with self.uow() as uow:
            return await uow.previews.get(post_id, index)
