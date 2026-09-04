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
    PublishTargets,
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


# -- Delivery: Freigabe state machine -----------------------------------------


def test_queue_for_review_moves_a_pending_delivery_to_review():
    d = Delivery(post_id="p1", destination=Destination("telegram", "c1"))

    d.queue_for_review()

    assert d.status == DeliveryStatus.REVIEW
    assert not d.can_retry()  # REVIEW is never retried by the poller


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.REVIEW, DeliveryStatus.SENT, DeliveryStatus.FAILED, DeliveryStatus.SKIPPED],
)
def test_queue_for_review_refuses_anything_but_pending(status):
    d = make_delivery(status)

    with pytest.raises(ValueError, match="cannot queue for review"):
        d.queue_for_review()


def test_approve_moves_a_review_delivery_back_to_pending():
    d = make_delivery(DeliveryStatus.REVIEW)

    d.approve()

    assert d.status == DeliveryStatus.PENDING


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.PENDING, DeliveryStatus.SENT, DeliveryStatus.FAILED, DeliveryStatus.SKIPPED],
)
def test_approve_refuses_anything_but_review(status):
    d = make_delivery(status)

    with pytest.raises(ValueError, match="cannot approve"):
        d.approve()


def test_reject_moves_a_review_delivery_to_skipped():
    d = make_delivery(DeliveryStatus.REVIEW)

    d.reject()

    assert d.status == DeliveryStatus.SKIPPED


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.PENDING, DeliveryStatus.SENT, DeliveryStatus.FAILED, DeliveryStatus.SKIPPED],
)
def test_reject_refuses_anything_but_review(status):
    d = make_delivery(status)

    with pytest.raises(ValueError, match="cannot reject"):
        d.reject()


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


def test_new_draft_stores_the_optional_event_ref():
    with_event = PostDraft.new("hello", [make_image()], NOW, event_ref="calendar:e1")
    without_event = PostDraft.new("hello", [make_image()], NOW)

    assert with_event.event_ref == "calendar:e1"
    assert without_event.event_ref is None


# -- PostDraft: Freigabe state machine -----------------------------------------

TARGETS = PublishTargets(instagram=False, destinations=(Destination("telegram", "c1"),))


def test_submit_for_review_stores_targets_and_moves_to_review():
    draft = PostDraft.new("hello", [make_image()], NOW)

    draft.submit_for_review(TARGETS)

    assert draft.status == DraftStatus.REVIEW
    assert draft.targets == TARGETS


@pytest.mark.parametrize("status", [DraftStatus.REVIEW, DraftStatus.PUBLISHED, DraftStatus.FAILED])
def test_submit_for_review_refuses_anything_but_draft(status):
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.status = status

    with pytest.raises(ValueError, match="cannot submit for review"):
        draft.submit_for_review(TARGETS)


def test_is_reviewable_is_true_for_review_with_targets():
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.submit_for_review(TARGETS)

    assert draft.is_reviewable()


def test_is_reviewable_is_true_for_failed_with_targets():
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.targets = TARGETS
    draft.mark_failed("boom")

    assert draft.is_reviewable()


def test_is_reviewable_is_false_without_targets():
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.status = DraftStatus.FAILED

    assert not draft.is_reviewable()


@pytest.mark.parametrize("status", [DraftStatus.DRAFT, DraftStatus.PUBLISHED])
def test_is_reviewable_is_false_for_draft_and_published_even_with_targets(status):
    draft = PostDraft.new("hello", [make_image()], NOW)
    draft.targets = TARGETS
    draft.status = status

    assert not draft.is_reviewable()
