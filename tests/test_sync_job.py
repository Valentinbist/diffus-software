"""SyncJob welds token refresh to the sync cadence.

The regression these guard: refresh used to be its own 24h scheduler job, so a
host restarting more often than daily never refreshed the token at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from connector.application.refresh_token import EnsureFreshToken
from connector.application.sync_posts import SyncPosts
from connector.domain.entities import MediaItem, MediaType, Post, Token
from connector.domain.errors import NotConnectedError
from connector.presentation.jobs import SyncJob
from tests.fakes import (
    FailingSource,
    FakeAuth,
    FakeDeliveries,
    FakeMedia,
    FakePosts,
    FakePreviews,
    FakeSink,
    FakeTokens,
    StaticSource,
)


def make_post(post_id: str) -> Post:
    return Post(
        id=post_id,
        caption="caption",
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url=f"https://cdn.example.com/{post_id}.jpg", type=MediaType.IMAGE),),
        posted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


def make_token(age_days: int) -> Token:
    now = datetime.now(UTC)
    return Token(
        access_token="original",
        ig_user_id="17841400000000000",
        expires_at=now + timedelta(days=60 - age_days),
        refreshed_at=now - timedelta(days=age_days),
    )


def make_job(source=None, sink=None, tokens=None, auth=None):
    source = source if source is not None else StaticSource([])
    sink = sink if sink is not None else FakeSink()
    tokens = tokens if tokens is not None else FakeTokens()
    auth = auth if auth is not None else FakeAuth()

    sync = SyncPosts(
        source=source,
        posts=FakePosts(),
        deliveries=FakeDeliveries(),
        media=FakeMedia(),
        previews=FakePreviews(),
        sink=sink,
        chat_ids=["chat1"],
    )
    refresh = EnsureFreshToken(auth=auth, tokens=tokens)
    return SyncJob(sync=sync, refresh=refresh), tokens, auth


async def test_run_refreshes_a_token_that_is_past_the_refresh_window():
    tokens = FakeTokens(make_token(age_days=55))
    job, tokens, auth = make_job(tokens=tokens)

    await job.run()

    assert auth.refresh_calls == 1
    assert tokens.token is not None
    assert tokens.token.access_token == "refreshed"


async def test_run_leaves_a_young_token_alone():
    tokens = FakeTokens(make_token(age_days=1))
    job, tokens, auth = make_job(tokens=tokens)

    await job.run()

    assert auth.refresh_calls == 0
    assert tokens.token is not None
    assert tokens.token.access_token == "original"


async def test_repeated_runs_keep_refreshing_so_a_restart_never_strands_the_token():
    # Every run is a refresh opportunity; the old 24h job needed a 24h-old
    # process to get even one.
    tokens = FakeTokens(make_token(age_days=55))
    job, tokens, auth = make_job(tokens=tokens)

    await job.run()
    await job.run()

    assert auth.refresh_calls == 1  # second run sees a fresh token
    assert tokens.token is not None
    assert tokens.token.refreshed_at > datetime.now(UTC) - timedelta(minutes=1)


async def test_sync_still_runs_when_refresh_fails():
    post = make_post("p1")
    sink = FakeSink()
    tokens = FakeTokens(make_token(age_days=55))
    job, _tokens, auth = make_job(
        source=StaticSource([post]), sink=sink, tokens=tokens, auth=FakeAuth(fail=True)
    )

    await job.run()  # must not raise

    assert auth.refresh_calls == 1


async def test_run_swallows_sync_failures_so_the_scheduler_survives():
    job, _tokens, _auth = make_job(source=FailingSource(RuntimeError("instagram is down")))

    await job.run()  # must not raise


async def test_run_swallows_not_connected():
    job, _tokens, _auth = make_job(source=FailingSource(NotConnectedError("no token")))

    await job.run()  # must not raise


# -- last_run: what the UI's status line is built from ----------------------


async def test_run_records_when_it_finished_cleanly():
    job, _tokens, _auth = make_job(tokens=FakeTokens(make_token(age_days=1)))

    await job.run()

    assert job.last_run is not None
    assert job.last_run.sync_error is None
    assert job.last_run.refresh_error is None
    assert job.last_run.at > datetime.now(UTC) - timedelta(minutes=1)


async def test_failed_sync_is_recorded_for_the_ui():
    job, _tokens, _auth = make_job(
        source=FailingSource(RuntimeError("instagram is down")),
        tokens=FakeTokens(make_token(age_days=1)),
    )

    await job.run()

    assert job.last_run is not None
    assert job.last_run.sync_error == "instagram is down"


async def test_failed_refresh_is_recorded_for_the_ui():
    job, _tokens, _auth = make_job(
        tokens=FakeTokens(make_token(age_days=55)), auth=FakeAuth(fail=True)
    )

    await job.run()

    assert job.last_run is not None
    assert job.last_run.refresh_error == "simulated refresh failure"
    assert job.last_run.sync_error is None


async def test_not_connected_does_not_count_as_a_run():
    job, _tokens, _auth = make_job(source=FailingSource(NotConnectedError("no token")))

    await job.run()

    assert job.last_run is None
