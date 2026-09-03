"""PostCatalog implemented over the crossposting context's own read use cases.

The one deliberate exception to "contexts never import each other's domain,
application or infrastructure": an adapter under a context's own
`infrastructure/` may call another context's `application/` read use cases,
because the application read side of a context is its public API (see
docs/architecture.md, Bounded contexts). `GetOverview` and `GetPostDetail`
are that public API for posts; the `DeliveryStatus` import is for the same
reason — deciding what "delivered" means from a raw delivery list is this
adapter's mapping job, not crossposting's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diffus.calendar.domain.entities import LinkablePost
from diffus.crossposting.application.overview import GetOverview, PostView
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.domain.entities import DeliveryStatus


def _to_linkable(view: PostView) -> LinkablePost:
    first = min(view.stored_previews, default=None)
    thumbnail_url = (
        f"/posts/{view.post.id}/media/{first}" if first is not None else view.post.cover_url
    )

    return LinkablePost(
        id=view.post.id,
        caption=view.post.caption,
        permalink=view.post.permalink,
        posted_at=view.post.posted_at,
        thumbnail_url=thumbnail_url,
        detail_url=f"/posts/{view.post.id}",
        delivered=any(d.status == DeliveryStatus.SENT for d in view.deliveries),
    )


@dataclass
class CrosspostingPostCatalog:
    overview: GetOverview
    detail: GetPostDetail

    async def recent(self, limit: int = 50) -> list[LinkablePost]:
        overview = await self.overview.run(limit=limit)
        return [_to_linkable(view) for view in overview.posts]

    async def by_ids(self, ids: Sequence[str]) -> dict[str, LinkablePost]:
        found: dict[str, LinkablePost] = {}
        for post_id in ids:
            view = await self.detail.run(post_id)
            if view is not None:
                found[post_id] = _to_linkable(view)
        return found
