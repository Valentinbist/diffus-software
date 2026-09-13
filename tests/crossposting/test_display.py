from __future__ import annotations

from datetime import UTC, datetime, timedelta

from diffus.crossposting.application.channels import InstagramChannel
from diffus.crossposting.application.deliver import DeliverPost
from diffus.crossposting.application.overview import PostView
from diffus.crossposting.application.refresh_token import EnsureFreshToken
from diffus.crossposting.application.sync_job import LastRun, SyncJob
from diffus.crossposting.application.sync_posts import SyncPosts, SyncReport
from diffus.crossposting.domain.entities import (
    INSTAGRAM_CHANNEL,
    Delivery,
    DeliveryStatus,
    Destination,
    LinkedEvent,
    MediaItem,
    MediaType,
    Post,
    ReviewLogEntry,
    ReviewOutcome,
)
from diffus.crossposting.domain.stats import ReviewStats
from diffus.crossposting.presentation.display import (
    ChannelLine,
    backdrop_url,
    channel_lines,
    delivery_label,
    filter_by_events,
    filter_by_source,
    inbox_zero_line,
    instagram_hint,
    job_status,
    outcome_line,
    reaction_line,
    sink_label,
    source_label,
    stored_cover,
    sync_summary,
    target_label,
)
from tests.crossposting.fakes import FakeAuth, FakeMedia, FakeSink, FakeUnitOfWork, StaticSource

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin (CEST)
TELEGRAM = Destination("telegram", "c1")


def test_stored_cover_is_the_first_media_item_with_a_stored_still():
    post = Post(
        id="p",
        source="instagram",
        caption=None,
        permalink="https://instagram.com/p/p/",
        media=(
            MediaItem(url="https://cdn.example.com/0.mp4", type=MediaType.VIDEO),
            MediaItem(url="https://cdn.example.com/1.jpg", type=MediaType.IMAGE),
        ),
        posted_at=NOW,
    )

    assert stored_cover(PostView(post=post, deliveries=[], stored_previews=frozenset({1}))) == 1
    assert stored_cover(PostView(post=post, deliveries=[], stored_previews=frozenset())) is None


def test_delivery_label_names_the_target_only_when_there_are_several():
    dest = Destination("telegram", "-100")
    sent = Delivery(post_id="p", destination=dest, status=DeliveryStatus.SENT)
    failed = Delivery(post_id="p", destination=dest, status=DeliveryStatus.FAILED)

    assert delivery_label(sent, multi_target=False) == "Telegram ✓"
    assert delivery_label(sent, multi_target=True) == "Telegram -100 ✓"
    assert delivery_label(failed, multi_target=False) == "Telegram ✕ nicht durchgekommen"


def test_sink_label_falls_back_to_capitalized_name_for_unknown_sinks():
    assert sink_label("telegram") == "Telegram"
    assert sink_label("signal") == "Signal"


def test_target_label_combines_sink_label_and_address():
    delivery = Delivery(post_id="p", destination=Destination("signal", "+49151"))

    assert target_label(delivery) == "Signal +49151"


def make_post_view(post_id: str, events: list[LinkedEvent] | None = None) -> PostView:
    post = Post(
        id=post_id,
        source="instagram",
        caption=None,
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=NOW,
    )
    return PostView(post=post, deliveries=[], events=events or [])


def test_filter_by_events_keeps_only_linked_or_only_unlinked_posts():
    event = LinkedEvent(id="e1", title="Plenum", starts_at=NOW, detail_url="/calendar/events/e1")
    linked = make_post_view("p1", events=[event])
    unlinked = make_post_view("p2")

    assert filter_by_events([linked, unlinked], "with") == [linked]
    assert filter_by_events([linked, unlinked], "without") == [unlinked]
    assert filter_by_events([linked, unlinked], "all") == [linked, unlinked]
    assert filter_by_events([linked, unlinked], "garbage") == [linked, unlinked]


def make_post_view_with_source(post_id: str, source: str) -> PostView:
    post = Post(
        id=post_id,
        source=source,
        caption=None,
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(),
        posted_at=NOW,
    )
    return PostView(post=post, deliveries=[])


def test_source_label_names_known_sources_and_falls_back_to_capitalized():
    assert source_label("instagram") == "Instagram"
    assert source_label("diffus") == "App"
    assert source_label("signal") == "Signal"


def test_filter_by_source_keeps_only_instagram_or_only_diffus_posts():
    ig = make_post_view_with_source("p1", "instagram")
    app = make_post_view_with_source("p2", "diffus")

    assert filter_by_source([ig, app], "instagram") == [ig]
    assert filter_by_source([ig, app], "diffus") == [app]
    assert filter_by_source([ig, app], "all") == [ig, app]
    assert filter_by_source([ig, app], "garbage") == [ig, app]


def test_delivery_label_for_a_review_row_says_freigabe_ausstehend():
    delivery = Delivery(
        post_id="p", destination=Destination("telegram", "c1"), status=DeliveryStatus.REVIEW
    )

    assert delivery_label(delivery, multi_target=False) == "Telegram · Freigabe ausstehend"
    assert delivery_label(delivery, multi_target=True) == "Telegram c1 · Freigabe ausstehend"


def test_delivery_label_for_instagram_never_names_the_address_even_multi_target():
    sent = Delivery(post_id="p", destination=INSTAGRAM_CHANNEL, status=DeliveryStatus.SENT)

    assert delivery_label(sent, multi_target=False) == "Instagram ✓"
    assert delivery_label(sent, multi_target=True) == "Instagram ✓"


def make_channel(
    connected: bool = True,
    can_publish: bool = True,
    public_https: bool = True,
) -> InstagramChannel:
    return InstagramChannel(
        destination=INSTAGRAM_CHANNEL,
        connected=connected,
        can_publish=can_publish,
        public_https=public_https,
        auto_publish=False,
    )


def test_instagram_hint_covers_all_four_states():
    assert instagram_hint(make_channel(connected=False)) == "Instagram ist nicht verbunden."
    assert (
        instagram_hint(make_channel(can_publish=False))
        == "Instagram neu verbinden, um Veröffentlichen freizuschalten."
    )
    assert instagram_hint(make_channel(public_https=False)) == (
        "PUBLIC_BASE_URL ist keine öffentliche https-Adresse – Instagram kann die Bilder "
        "nicht laden. Telegram geht trotzdem."
    )
    assert instagram_hint(make_channel()) is None


# -- channel_lines --------------------------------------------------------------


def make_post_with_source(source: str, permalink: str = "https://instagram.com/p/p1/") -> Post:
    return Post(
        id="p1", source=source, caption=None, permalink=permalink, media=(), posted_at=NOW
    )


def test_channel_lines_for_an_instagram_post_starts_with_the_origin_line():
    post = make_post_with_source("instagram")
    dest = Destination("telegram", "c1")
    sent = Delivery(post_id="p1", destination=dest, status=DeliveryStatus.SENT)

    lines = channel_lines(PostView(post=post, deliveries=[sent]), multi_target=False)

    assert lines[0] == ChannelLine(
        "Instagram ✓", ok=True, attention=False, href="https://instagram.com/p/p1/"
    )
    assert lines[1] == ChannelLine("Telegram ✓", ok=True, attention=False, href=None)


def test_channel_lines_for_an_app_post_has_no_origin_line():
    post = make_post_with_source("diffus")

    lines = channel_lines(PostView(post=post, deliveries=[]), multi_target=False)

    assert lines == []


def test_channel_lines_marks_a_failed_delivery_with_attention_and_not_ok():
    post = make_post_with_source("diffus")
    failed = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.FAILED
    )

    [line] = channel_lines(PostView(post=post, deliveries=[failed]), multi_target=False)

    assert line.ok is False
    assert line.attention is True
    assert line.href is None


def test_channel_lines_orders_deliveries_by_destination():
    post = make_post_with_source("diffus")
    c2 = Delivery(
        post_id="p1", destination=Destination("telegram", "c2"), status=DeliveryStatus.SENT
    )
    c1 = Delivery(
        post_id="p1", destination=Destination("telegram", "c1"), status=DeliveryStatus.SENT
    )

    lines = channel_lines(PostView(post=post, deliveries=[c2, c1]), multi_target=True)

    assert [line.label for line in lines] == ["Telegram c1 ✓", "Telegram c2 ✓"]


# -- sync_summary ---------------------------------------------------------------


def test_sync_summary_with_no_report_is_empty():
    assert sync_summary(None) == ""


def test_sync_summary_with_nothing_to_say():
    assert sync_summary(SyncReport()) == "Nichts Neues"


def test_sync_summary_singular_new_post():
    assert sync_summary(SyncReport(new=1)) == "1 neuer Post"


def test_sync_summary_joins_every_nonzero_part_in_order():
    report = SyncReport(new=2, sent=1, queued=1, failed=1, skipped=1)

    assert sync_summary(report) == (
        "2 neue Posts · 1 zugestellt · 1 wartet auf Freigabe · "
        "1 nicht durchgekommen · 1 übersprungen"
    )


def test_sync_summary_queued_plural():
    assert sync_summary(SyncReport(queued=3)) == "3 warten auf Freigabe"


# -- job_status (crossposting) ---------------------------------------------------


def make_sync_job() -> SyncJob:
    uow = FakeUnitOfWork()
    media = FakeMedia()
    deliver = DeliverPost(media=media, sinks={"telegram": FakeSink()}, uow=uow)
    sync = SyncPosts(
        source=StaticSource([]), media=media, deliver=deliver, destinations=[TELEGRAM], uow=uow
    )
    return SyncJob(sync=sync, refresh=EnsureFreshToken(auth=FakeAuth(), uow=uow))


def test_job_status_has_the_instagram_label_and_sync_action():
    status = job_status(make_sync_job())

    assert status.key == "posts"
    assert status.label == "Instagram-Abgleich"
    assert status.sync_action == "/sync"
    assert status.last is None


def test_job_status_runs_are_newest_first_and_summarised():
    job = make_sync_job()
    older = LastRun(at=NOW - timedelta(hours=1), report=SyncReport(new=1))
    newer = LastRun(at=NOW, report=SyncReport(sent=2))
    job.runs.append(older)
    job.runs.append(newer)

    status = job_status(job)

    assert [run.at for run in status.runs] == [NOW, NOW - timedelta(hours=1)]
    assert status.last is not None
    assert status.last.at == NOW
    assert status.last.summary == "2 zugestellt"


def test_job_status_error_prefers_sync_error_over_refresh_error():
    job = make_sync_job()
    job.runs.append(LastRun(at=NOW, sync_error="sync boom", refresh_error="refresh boom"))

    status = job_status(job)

    assert status.last is not None
    assert status.last.error == "sync boom"


def test_job_status_error_names_a_refresh_only_failure():
    job = make_sync_job()
    job.runs.append(LastRun(at=NOW, refresh_error="refresh boom"))

    status = job_status(job)

    assert status.last is not None
    assert status.last.error == "Token-Auffrischung fehlgeschlagen: refresh boom"


def test_job_status_no_error_when_the_run_went_through():
    job = make_sync_job()
    job.runs.append(LastRun(at=NOW, report=SyncReport()))

    status = job_status(job)

    assert status.last is not None
    assert status.last.error is None


# -- outcome_line -----------------------------------------------------------------


def test_outcome_line_rejected_has_no_arrow():
    entry = ReviewLogEntry.new("draft", ReviewOutcome.REJECTED, "x", (), NOW)

    assert outcome_line(entry, multi_target=False) == "Abgelehnt"


def test_outcome_line_approved_names_the_targets_sorted():
    signal = Destination("signal", "s1")
    entry = ReviewLogEntry.new(
        "post", ReviewOutcome.APPROVED, "x", (TELEGRAM, signal), NOW, post_id="p1"
    )

    # "signal" sorts before "telegram"; multi_target=False bares both labels.
    assert outcome_line(entry, multi_target=False) == "Freigegeben → Signal, Telegram"


def test_outcome_line_auto_says_automatisch_veroeffentlicht():
    entry = ReviewLogEntry.new("post", ReviewOutcome.AUTO, "x", (TELEGRAM,), NOW, post_id="p1")

    assert outcome_line(entry, multi_target=False) == "Automatisch veröffentlicht → Telegram"


def test_outcome_line_instagram_never_shows_its_address_even_multi_target():
    entry = ReviewLogEntry.new(
        "draft", ReviewOutcome.APPROVED, "x", (INSTAGRAM_CHANNEL, TELEGRAM), NOW, post_id="p1"
    )

    assert outcome_line(entry, multi_target=True) == "Freigegeben → Instagram, Telegram c1"


# -- backdrop_url -----------------------------------------------------------------


def make_post_view_with_cover(post_id: str, stored: bool) -> PostView:
    post = Post(
        id=post_id,
        source="instagram",
        caption=None,
        permalink=f"https://instagram.com/p/{post_id}/",
        media=(MediaItem(url="https://cdn.example.com/x.jpg", type=MediaType.IMAGE),),
        posted_at=NOW,
    )
    previews = frozenset({0}) if stored else frozenset()
    return PostView(post=post, deliveries=[], stored_previews=previews)


def test_backdrop_url_is_none_without_any_stored_preview():
    views = [
        make_post_view_with_cover("p1", stored=False),
        make_post_view_with_cover("p2", stored=False),
    ]

    assert backdrop_url(views) is None


def test_backdrop_url_is_the_first_view_with_a_stored_cover():
    views = [
        make_post_view_with_cover("p1", stored=False),
        make_post_view_with_cover("p2", stored=True),
        make_post_view_with_cover("p3", stored=True),
    ]

    assert backdrop_url(views) == "/posts/p2/media/0"


def test_backdrop_url_is_none_with_no_posts_at_all():
    assert backdrop_url([]) is None


# -- inbox_zero_line ---------------------------------------------------------------


def make_stats(
    empty_since: datetime | None = None, longest_empty: timedelta | None = None
) -> ReviewStats:
    return ReviewStats(
        decisions=0,
        decided_today=0,
        empty_since=empty_since,
        longest_empty=longest_empty,
        mean_reaction=None,
        fastest_reaction=None,
        reactions=0,
    )


def test_inbox_zero_line_is_none_without_any_decision():
    assert inbox_zero_line(make_stats(), NOW) is None


def test_inbox_zero_line_just_emptied():
    stats = make_stats(empty_since=NOW - timedelta(seconds=30))

    assert inbox_zero_line(stats, NOW) == "Gerade erst geleert."


def test_inbox_zero_line_without_a_known_record():
    stats = make_stats(empty_since=NOW - timedelta(minutes=5))

    assert inbox_zero_line(stats, NOW) == "Seit 5 Minuten leer."


def test_inbox_zero_line_at_or_past_the_record():
    stats = make_stats(empty_since=NOW - timedelta(hours=2), longest_empty=timedelta(hours=1))

    assert inbox_zero_line(stats, NOW) == "Seit 2 h leer – Rekord."


def test_inbox_zero_line_short_of_the_record_names_it():
    stats = make_stats(empty_since=NOW - timedelta(minutes=30), longest_empty=timedelta(hours=2))

    assert inbox_zero_line(stats, NOW) == "Seit 30 Minuten leer. Rekord: 2 h."


# -- reaction_line -----------------------------------------------------------------


def test_reaction_line_is_none_without_any_reaction():
    assert reaction_line(make_stats()) is None


def test_reaction_line_singular_reaction():
    stats = ReviewStats(
        decisions=1,
        decided_today=1,
        empty_since=NOW,
        longest_empty=None,
        mean_reaction=timedelta(minutes=5),
        fastest_reaction=timedelta(minutes=5),
        reactions=1,
    )

    assert reaction_line(stats) == "Entschieden nach 5 Minuten."


def test_reaction_line_several_reactions_shows_mean_and_record():
    stats = ReviewStats(
        decisions=3,
        decided_today=0,
        empty_since=NOW,
        longest_empty=None,
        mean_reaction=timedelta(minutes=12),
        fastest_reaction=timedelta(minutes=2),
        reactions=3,
    )

    assert reaction_line(stats) == "Im Schnitt nach 12 Minuten entschieden, Rekord 2 Minuten."
