"""CrosspostingPostCatalog: PostCatalog implemented over crossposting's own read use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from diffus.calendar.infrastructure.crossposting import CrosspostingPostCatalog
from diffus.crossposting.application.overview import GetOverview
from diffus.crossposting.application.post_detail import GetPostDetail
from diffus.crossposting.domain.entities import (
    Delivery,
    Destination,
    MediaItem,
    MediaType,
    Post,
    Preview,
)
from tests.crossposting.fakes import FakeUnitOfWork


async def make_catalog() -> CrosspostingPostCatalog:
    uow = FakeUnitOfWork()
    post = Post(
        id="p1",
        source="instagram",
        caption="Siebdruck-Nachmittag",
        permalink="https://instagram.com/p/p1/",
        media=(
            MediaItem(url="https://cdn.example.com/0.jpg", type=MediaType.IMAGE),
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
        ),
        posted_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
    await uow.posts.upsert(post)
    # Stored preview at index 1, not 0: thumbnail_url must pick the lowest
    # *stored* index, not blindly assume media index 0 has one.
    await uow.previews.save(Preview(post_id="p1", index=1, content_type="image/jpeg", data=b"x"))
    delivery = Delivery(post_id="p1", destination=Destination("telegram", "c1"))
    delivery.record_sent(datetime(2026, 8, 20, 12, 5, tzinfo=UTC))
    await uow.deliveries.save(delivery)
    await uow.commit()

    return CrosspostingPostCatalog(
        overview=GetOverview(uow=uow, source="instagram"), detail=GetPostDetail(uow=uow)
    )


async def test_recent_maps_the_lowest_stored_preview_index_to_a_thumbnail_route():
    catalog = await make_catalog()

    posts = await catalog.recent(limit=50)

    assert len(posts) == 1
    linkable = posts[0]
    assert linkable.id == "p1"
    assert linkable.thumbnail_url == "/posts/p1/media/1"
    assert linkable.detail_url == "/posts/p1"
    assert linkable.delivered is True


async def test_by_ids_skips_unknown_posts():
    catalog = await make_catalog()

    found = await catalog.by_ids(["p1", "nope"])

    assert set(found) == {"p1"}
    assert found["p1"].permalink == "https://instagram.com/p/p1/"


async def test_thumbnail_falls_back_to_the_cover_url_without_a_stored_preview():
    uow = FakeUnitOfWork()
    post = Post(
        id="p2",
        source="instagram",
        caption=None,
        permalink="https://instagram.com/p/p2/",
        media=(MediaItem(url="https://cdn.example.com/cover.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
    )
    await uow.posts.upsert(post)
    await uow.commit()
    catalog = CrosspostingPostCatalog(
        overview=GetOverview(uow=uow, source="instagram"), detail=GetPostDetail(uow=uow)
    )

    posts = await catalog.recent()

    assert posts[0].thumbnail_url == "https://cdn.example.com/cover.jpg"
    assert posts[0].delivered is False
