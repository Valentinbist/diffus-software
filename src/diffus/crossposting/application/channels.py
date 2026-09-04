"""Use cases: what channels exist, and the per-channel auto-publish switch.

Replaces publish_readiness.py's GetPublishReadiness now that Instagram is
just one more channel with a switch, not a special case: GetChannels answers
both "can we publish to Instagram at all" (connected/can_publish/public_https,
unchanged from before) and "is each channel set to auto-publish", in one call,
so the Social Posts and compose-wizard pages don't need two round trips.
`all_auto` is the pure helper the drafting and sync use cases both consult to
decide immediate publish vs. Freigabe — kept here, not on PublishTargets
itself, because it needs the stored switches to answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from diffus.crossposting.domain.entities import INSTAGRAM_CHANNEL, Destination, PublishTargets
from diffus.crossposting.domain.ports import UnitOfWorkFactory


def all_auto(auto: Mapping[Destination, bool], targets: PublishTargets) -> bool:
    """True when every channel `targets` chose has its auto-publish switch on.

    A destination missing from `auto` (never touched in channel_settings)
    counts as off — see the migration docstring, "default off".
    """
    chosen: list[Destination] = list(targets.destinations)
    if targets.instagram:
        chosen.append(INSTAGRAM_CHANNEL)
    return all(auto.get(d, False) for d in chosen)


@dataclass(frozen=True, slots=True)
class InstagramChannel:
    destination: Destination
    connected: bool
    can_publish: bool
    public_https: bool
    auto_publish: bool


@dataclass(frozen=True, slots=True)
class TelegramChannel:
    destination: Destination
    label: str
    auto_publish: bool


@dataclass(frozen=True, slots=True)
class Channels:
    instagram: InstagramChannel
    telegram: tuple[TelegramChannel, ...]

    def auto_map(self) -> dict[Destination, bool]:
        """Every known channel's current switch — what SetAutoPublish needs to know is "known"."""
        result = {self.instagram.destination: self.instagram.auto_publish}
        result.update({channel.destination: channel.auto_publish for channel in self.telegram})
        return result


@dataclass
class GetChannels:
    uow: UnitOfWorkFactory
    source: str
    destinations: Sequence[Destination]
    public_base_url: str

    async def run(self) -> Channels:
        async with self.uow() as uow:
            token = await uow.tokens.get(self.source)
            auto = await uow.channels.get_all()

        instagram = InstagramChannel(
            destination=INSTAGRAM_CHANNEL,
            connected=token is not None,
            can_publish=token is not None and token.can_publish,
            public_https=self.public_base_url.startswith("https://"),
            # The switch may be on even while Instagram isn't connected: it's
            # a policy for once it is, not a readiness signal (§6a).
            auto_publish=auto.get(INSTAGRAM_CHANNEL, False),
        )
        single = len(self.destinations) == 1
        telegram = tuple(
            TelegramChannel(
                destination=d,
                label="Telegram" if single else f"Telegram {d.address}",
                auto_publish=auto.get(d, False),
            )
            for d in self.destinations
        )
        return Channels(instagram=instagram, telegram=telegram)


@dataclass
class SetAutoPublish:
    uow: UnitOfWorkFactory
    channels: Sequence[Destination]

    async def run(self, enabled: set[Destination]) -> None:
        """Full-set semantics: every known channel is written, on or off; unknowns are ignored.

        A checkbox form only submits the boxes that are checked, so "not in
        `enabled`" is what an unchecked box looks like — there is no
        difference between "explicitly off" and "not mentioned" on the wire.
        """
        async with self.uow() as uow:
            for destination in self.channels:
                await uow.channels.set(destination, destination in enabled)
            await uow.commit()
