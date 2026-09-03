"""ConnectInstagram: the OAuth connect flow's use case, against fakes."""

from __future__ import annotations

from diffus.crossposting.application.connect_instagram import ConnectInstagram
from tests.crossposting.fakes import FakeAuth, FakeUnitOfWork


def make_connect(auth=None):
    auth = auth if auth is not None else FakeAuth()
    uow = FakeUnitOfWork()
    return ConnectInstagram(auth=auth, uow=uow), uow, auth


def test_authorize_url_passes_through_to_the_auth_gateway():
    connect, _uow, auth = make_connect()

    assert connect.authorize_url() == auth.authorize_url()


async def test_complete_stores_the_token_under_the_source_and_commits():
    connect, uow, auth = make_connect()

    token = await connect.complete("some-code")

    assert auth.exchanged_codes == ["some-code"]
    assert token.source == "instagram"
    assert (await uow.tokens.get("instagram")) == token
    assert uow.commits >= 1
