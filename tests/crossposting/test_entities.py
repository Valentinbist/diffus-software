"""Behaviour that lives on the domain objects themselves: no ports, no fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diffus.crossposting.domain.entities import (
    AccessToken,
    Delivery,
    DeliveryStatus,
    Destination,
    DraftImage,
    DraftStatus,
    PostDraft,
    Token,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


# -- Destination -------------------------------------------------------------


def test_destination_round_trips_through_its_text_form():
    dest = Destination(sink="telegram", address="-1001234567890")

    assert str(dest) == "telegram:-1001234567890"
    assert Destination.parse(str(dest)) == dest


def test_destination_parse_keeps_colons_inside_the_address():
    assert Destination.parse("signal:+49:151") == Destination("signal", "+49:151")


@pytest.mark.parametrize("text", ["", "telegram", ":x", "x:", "telegram:"])
def test_destination_parse_rejects_incomplete_text(text):
    with pytest.raises(ValueError):
        Destination.parse(text)


def test_destinations_sort_by_sink_then_address():
    ordered = sorted(
        [Destination("telegram", "b"), Destination("signal", "z"), Destination("telegram", "a")]
    )
    assert ordered == [
        Destination("signal", "z"),
        Destination("telegram", "a"),
        Destination("telegram", "b"),
    ]


# -- Delivery ----------------------------------------------------------------


def make_delivery(status: DeliveryStatus, attempts: int = 0) -> Delivery:
    return Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=status, attempts=attempts
    )


def test_new_delivery_is_pending_with_no_attempts():
    d = Delivery(post_id="p1", destination=Destination("telegram", "c1"))
    assert d.status == DeliveryStatus.PENDING
    assert d.attempts == 0
    assert not d.can_retry()


@pytest.mark.parametrize(
    "status", [DeliveryStatus.SENT, DeliveryStatus.SKIPPED, DeliveryStatus.PENDING]
)
def test_only_failed_deliveries_can_be_retried(status):
    assert not make_delivery(status).can_retry()


def test_failed_delivery_retries_until_the_attempt_cap():
    assert make_delivery(DeliveryStatus.FAILED, attempts=4).can_retry()
    assert not make_delivery(DeliveryStatus.FAILED, attempts=Delivery.MAX_ATTEMPTS).can_retry()


def test_record_failure_counts_the_attempt_and_truncates_the_error():
    d = Delivery(post_id="p1", destination=Destination("telegram", "c1"))

    d.record_failure("x" * 5000)

    assert d.status == DeliveryStatus.FAILED
    assert d.attempts == 1
    assert d.error is not None
    assert len(d.error) == Delivery.MAX_ERROR_LENGTH


def test_record_sent_clears_the_error_and_stamps_the_time():
    d = make_delivery(DeliveryStatus.FAILED, attempts=2)
    d.error = "boom"

    d.record_sent(NOW)

    assert d.status == DeliveryStatus.SENT
    assert d.sent_at == NOW
    assert d.error is None
    assert d.attempts == 2  # history is kept


def test_skip_marks_seen_without_sending():
    d = Delivery(post_id="p1", destination=Destination("telegram", "c1"))
    d.skip()
    assert d.status == DeliveryStatus.SKIPPED
    assert not d.can_retry()


# -- AccessToken -------------------------------------------------------------


def test_access_token_never_prints_its_secret():
    token = AccessToken("IGQVJ-secret")

    assert "secret" not in repr(token)
    assert "secret" not in str(token)
    assert "secret" not in f"{token}"
    assert token.value == "IGQVJ-secret"
    assert token == AccessToken("IGQVJ-secret")


# -- Token -------------------------------------------------------------------


def make_token(age_days: int, days_left: int = 60) -> Token:
    return Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=NOW + timedelta(days=days_left),
        refreshed_at=NOW - timedelta(days=age_days),
    )


def test_token_refreshes_once_the_timer_is_reached():
    assert not make_token(age_days=49).needs_refresh(NOW)
    assert make_token(age_days=50).needs_refresh(NOW)


def test_token_refreshes_when_expiry_is_close_even_if_recently_refreshed():
    assert not make_token(age_days=1, days_left=8).needs_refresh(NOW)
    assert make_token(age_days=1, days_left=7).needs_refresh(NOW)


def test_token_can_publish_only_with_the_publish_scope():
    connected = make_token(age_days=1)
    assert not connected.can_publish

    with_basic_only = Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=NOW + timedelta(days=60),
        refreshed_at=NOW,
        scopes="instagram_business_basic",
    )
    assert not with_basic_only.can_publish

    with_publish = Token(
        source="instagram",
        access_token=AccessToken("t"),
        external_user_id="1",
        expires_at=NOW + timedelta(days=60),
        refreshed_at=NOW,
        scopes="instagram_business_basic,instagram_business_content_publish",
    )
    assert with_publish.can_publish


# -- PostDraft -----------------------------------------------------------------


def make_image(marker: bytes = b"data") -> DraftImage:
    return DraftImage(content_type="image/jpeg", width=100, height=100, data=marker)


def test_new_draft_gets_a_fresh_id_and_public_key_each_time():
    a = PostDraft.new("hello", [make_image()], NOW)
    b = PostDraft.new("hello", [make_image()], NOW)

    assert a.id != b.id
    assert a.public_key != b.public_key
    assert a.status == DraftStatus.DRAFT
    assert a.created_at == NOW
    assert a.post_id is None
    assert a.published_at is None


def test_public_media_url_carries_the_draft_id_index_and_key():
    draft = PostDraft.new("hello", [make_image()], NOW)

    url = draft.public_media_url("https://example.com", 2)

    assert url == f"https://example.com/media/drafts/{draft.id}/2?key={draft.public_key}"


def test_public_media_url_strips_a_trailing_slash_from_the_base():
    draft = PostDraft.new("hello", [make_image()], NOW)

    assert draft.public_media_url("https://example.com/", 0) == (
        f"https://example.com/media/drafts/{draft.id}/0?key={draft.public_key}"
    )


def test_mark_published_sets_the_post_id_time_and_clears_any_error():
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.mark_failed("boom")

    draft.mark_published("p1", NOW)

    assert draft.status == DraftStatus.PUBLISHED
    assert draft.post_id == "p1"
    assert draft.published_at == NOW
    assert draft.error is None


def test_mark_failed_sets_the_status_and_truncates_a_long_error():
    draft = PostDraft.new("hello", [make_image()], NOW)

    draft.mark_failed("x" * 5000)

    assert draft.status == DraftStatus.FAILED
    assert draft.error is not None
    assert len(draft.error) == Delivery.MAX_ERROR_LENGTH
