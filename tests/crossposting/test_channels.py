"""GetChannels, SetAutoPublish and the all_auto helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diffus.crossposting.application.channels import (
    GetChannels,
    SetAutoPublish,
    TelegramChannel,
    all_auto,
)
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    AccessToken,
    Destination,
    PublishTargets,
    Token,
)
from tests.crossposting.fakes import FakeChannels, FakeTokens, FakeUnitOfWork

C1 = Destination("telegram", "c1")
C2 = Destination("telegram", "c2")


def make_token(can_publish: bool = True) -> Token:
    now = datetime.now(UTC)
    return Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=now + timedelta(days=60),
        refreshed_at=now,
        scopes=Token.PUBLISH_SCOPE if can_publish else "",
    )


# -- GetChannels ----------------------------------------------------------------


async def test_instagram_channel_reports_not_connected_when_there_is_no_token():
    uow = FakeUnitOfWork()
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1], public_base_url="https://example.com"
    ).run()

    assert not channels.instagram.connected
    assert not channels.instagram.can_publish
    assert channels.instagram.destination == INSTAGRAM_CHANNEL


async def test_instagram_channel_reports_can_publish_and_public_https():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token(can_publish=True)))
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1], public_base_url="https://example.com"
    ).run()

    assert channels.instagram.connected
    assert channels.instagram.can_publish
    assert channels.instagram.public_https


async def test_instagram_channel_reports_no_public_https_for_a_plain_http_base_url():
    uow = FakeUnitOfWork(tokens=FakeTokens(make_token()))
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1], public_base_url="http://localhost:8000"
    ).run()

    assert not channels.instagram.public_https


async def test_instagram_switch_can_be_on_even_while_not_connected():
    uow = FakeUnitOfWork(channels=FakeChannels({INSTAGRAM_CHANNEL: True}))
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1], public_base_url="https://example.com"
    ).run()

    assert not channels.instagram.connected
    assert channels.instagram.auto_publish


async def test_a_single_telegram_destination_is_labelled_plainly():
    uow = FakeUnitOfWork()
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1], public_base_url="https://example.com"
    ).run()

    assert channels.telegram == (
        TelegramChannel(destination=C1, label="Telegram", auto_publish=False),
    )


async def test_multiple_telegram_destinations_are_labelled_by_address():
    uow = FakeUnitOfWork(channels=FakeChannels({C1: True}))
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1, C2], public_base_url="https://example.com"
    ).run()

    labels = {c.destination: c.label for c in channels.telegram}
    assert labels == {C1: "Telegram c1", C2: "Telegram c2"}
    autos = {c.destination: c.auto_publish for c in channels.telegram}
    assert autos == {C1: True, C2: False}


async def test_auto_map_combines_instagram_and_every_telegram_channel():
    uow = FakeUnitOfWork(channels=FakeChannels({INSTAGRAM_CHANNEL: True, C1: True, C2: False}))
    channels = await GetChannels(
        uow=uow, source="instagram", destinations=[C1, C2], public_base_url="https://example.com"
    ).run()

    assert channels.auto_map() == {INSTAGRAM_CHANNEL: True, C1: True, C2: False}


# -- SetAutoPublish: full-set semantics -----------------------------------------


async def test_set_auto_publish_writes_every_known_channel_on_or_off():
    uow = FakeUnitOfWork()
    set_auto = SetAutoPublish(uow=uow, channels=[INSTAGRAM_CHANNEL, C1, C2])

    await set_auto.run({C1})

    assert await uow.channels.get_all() == {INSTAGRAM_CHANNEL: False, C1: True, C2: False}


async def test_set_auto_publish_ignores_an_unknown_destination_in_enabled():
    uow = FakeUnitOfWork()
    set_auto = SetAutoPublish(uow=uow, channels=[C1])

    await set_auto.run({C1, Destination("telegram", "not-configured")})

    assert await uow.channels.get_all() == {C1: True}


async def test_set_auto_publish_commits_once():
    uow = FakeUnitOfWork()
    set_auto = SetAutoPublish(uow=uow, channels=[C1, C2])

    await set_auto.run(set())

    assert uow.commits == 1
    assert await uow.channels.get_all() == {C1: False, C2: False}


# -- all_auto truth table --------------------------------------------------------


@pytest.mark.parametrize(
    ("auto", "targets", "expected"),
    [
        # No channel touched at all: nothing chosen is auto.
        ({}, PublishTargets(instagram=False, destinations=(C1,)), False),
        # Exactly the chosen channel is auto.
        ({C1: True}, PublishTargets(instagram=False, destinations=(C1,)), True),
        # Chosen channel explicitly off.
        ({C1: False}, PublishTargets(instagram=False, destinations=(C1,)), False),
        # Two chosen, both auto.
        (
            {C1: True, C2: True},
            PublishTargets(instagram=False, destinations=(C1, C2)),
            True,
        ),
        # Two chosen, one not auto.
        (
            {C1: True, C2: False},
            PublishTargets(instagram=False, destinations=(C1, C2)),
            False,
        ),
        # Instagram chosen and auto, Telegram not chosen at all.
        ({INSTAGRAM_CHANNEL: True}, PublishTargets(instagram=True, destinations=()), True),
        # Instagram chosen but not auto.
        ({INSTAGRAM_CHANNEL: False}, PublishTargets(instagram=True, destinations=()), False),
        # Instagram auto, but a chosen Telegram channel is not: overall false.
        (
            {INSTAGRAM_CHANNEL: True, C1: False},
            PublishTargets(instagram=True, destinations=(C1,)),
            False,
        ),
        # Nothing chosen at all: vacuously true (callers guard this separately).
        ({}, PublishTargets(instagram=False, destinations=()), True),
    ],
)
def test_all_auto_truth_table(auto, targets, expected):
    assert all_auto(auto, targets) is expected
