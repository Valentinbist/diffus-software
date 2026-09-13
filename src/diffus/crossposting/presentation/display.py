"""Formatting for the UI: German, human-scale, matching the Crossposting mockups.

Pure functions that take `now` explicitly so they are trivially testable. Wired
into Jinja as filters by presentation/routes.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from diffus.crossposting.application.channels import InstagramChannel
from diffus.crossposting.application.overview import PostView
from diffus.crossposting.application.sync_job import LastRun, SyncJob
from diffus.crossposting.application.sync_posts import SyncReport
from diffus.crossposting.domain.entities import (
    Delivery,
    DeliveryStatus,
    Destination,
    ReviewLogEntry,
    ReviewOutcome,
)
from diffus.crossposting.domain.stats import ReviewStats
from diffus.shared.automation import JobRun, JobStatus
from diffus.shared.presentation.display import format_duration

# Sinks the connector knows how to label. A sink with no entry falls back to
# its name, capitalized, so a new adapter renders sanely before display.py
# is ever updated for it.
SINK_LABELS = {"telegram": "Telegram", "instagram": "Instagram"}

EVENT_OPTIONS = (("all", "Alle"), ("with", "Mit Termin"), ("without", "Ohne Termin"))

# A post's origin: Instagram (polled) or the app's own wizard (source="diffus").
SOURCE_LABELS = {"instagram": "Instagram", "diffus": "App"}
SOURCE_OPTIONS = (("all", "Alle"), ("instagram", "Instagram"), ("diffus", "App"))


def source_label(source: str) -> str:
    """'Instagram' / 'App' for a known source, otherwise the name capitalized."""
    return SOURCE_LABELS.get(source, source.capitalize())


def filter_by_events(views: Sequence[PostView], mode: str) -> list[PostView]:
    """Keep posts with ('with') or without ('without') a linked event; anything else keeps all."""
    if mode == "with":
        return [v for v in views if v.events]
    if mode == "without":
        return [v for v in views if not v.events]
    return list(views)


def filter_by_source(views: Sequence[PostView], mode: str) -> list[PostView]:
    """Keep posts whose source is 'instagram' or 'diffus'; anything else keeps all."""
    if mode in SOURCE_LABELS:
        return [v for v in views if v.post.source == mode]
    return list(views)

# What a delivery row says after the sink/target label. The mockups use ✓ / ✕ and plain words.
STATUS_TEXT = {
    DeliveryStatus.SENT: "✓",
    DeliveryStatus.FAILED: "✕ nicht durchgekommen",
    DeliveryStatus.PENDING: "… wird gesendet",
    DeliveryStatus.SKIPPED: "– übersprungen",
    DeliveryStatus.REVIEW: "· Freigabe ausstehend",
}


def stored_cover(view: PostView) -> int | None:
    """Index of the first media item the connector holds a still image for."""
    return next((i for i in range(len(view.post.media)) if i in view.stored_previews), None)


def backdrop_url(views: Sequence[PostView]) -> str | None:
    """The newest post's stored cover, for the site-wide blurred backdrop (`GET /backdrop`).

    Never the CDN URL: a CSS background-image can't carry the `<img>`s' own
    referrerpolicy, and the CDN link may already be dead by the time this is
    fetched — only a stored preview is safe to hotlink from a stylesheet.
    """
    for view in views:
        index = stored_cover(view)
        if index is not None:
            return f"/posts/{view.post.id}/media/{index}"
    return None


def sink_label(sink: str) -> str:
    """'Telegram' for a known sink, otherwise the name capitalized."""
    return SINK_LABELS.get(sink, sink.capitalize())


def target_label(delivery: Delivery) -> str:
    """'Telegram -100...' — the sink label plus the address it went to."""
    return f"{sink_label(delivery.destination.sink)} {delivery.destination.address}"


def delivery_label(delivery: Delivery, multi_target: bool) -> str:
    """'Telegram ✓', or 'Telegram <address> ✓' when more than one target is configured.

    The Instagram sink is always the bare label ("Instagram ✓"), even when
    multi_target: there is only ever one Instagram channel (INSTAGRAM_CHANNEL,
    the fixed "account" address), so naming the address would just repeat it.
    """
    if multi_target and delivery.destination.sink != "instagram":
        target = target_label(delivery)
    else:
        target = sink_label(delivery.destination.sink)
    return f"{target} {STATUS_TEXT[delivery.status]}"


@dataclass(frozen=True, slots=True)
class ChannelLine:
    """One line of 'where does this post stand': an origin fact, or a delivery attempt."""

    label: str
    ok: bool
    attention: bool
    # Only the Instagram-origin line has one, to the post's own permalink;
    # a delivery line never links anywhere.
    href: str | None


def channel_lines(view: PostView, multi_target: bool) -> list[ChannelLine]:
    """The post's Instagram origin (if any), then its deliveries, destination-sorted.

    A post polled from Instagram was never "delivered" there by this app —
    it's the origin, not a Delivery row — so without this, a polled post's
    own channel list would silently omit Instagram entirely (see the round 4
    plan, "Instagram-origin indicator").
    """
    lines = []
    if view.post.source == "instagram":
        lines.append(
            ChannelLine("Instagram ✓", ok=True, attention=False, href=view.post.permalink or None)
        )
    deliveries = sorted(view.deliveries, key=lambda d: d.destination)
    lines += [
        ChannelLine(
            label=delivery_label(d, multi_target),
            ok=d.status == DeliveryStatus.SENT,
            attention=d.status == DeliveryStatus.FAILED,
            href=None,
        )
        for d in deliveries
    ]
    return lines


def sync_summary(report: SyncReport | None) -> str:
    """Human summary of one Instagram sync run, e.g. '2 neue Posts · 1 zugestellt'.

    None (no report — the run errored before one was produced) summarises as
    "": a `JobRun`'s summary is never shown for an errored run in the first
    place (see settings.html), so there is nothing to say.
    """
    if report is None:
        return ""
    parts: list[str] = []
    if report.new:
        parts.append("1 neuer Post" if report.new == 1 else f"{report.new} neue Posts")
    if report.sent:
        parts.append(f"{report.sent} zugestellt")
    if report.queued:
        parts.append(
            "1 wartet auf Freigabe"
            if report.queued == 1
            else f"{report.queued} warten auf Freigabe"
        )
    if report.failed:
        parts.append(f"{report.failed} nicht durchgekommen")
    if report.skipped:
        parts.append(f"{report.skipped} übersprungen")
    return " · ".join(parts) if parts else "Nichts Neues"


def _run_error(run: LastRun) -> str | None:
    """sync_error wins; a refresh-only failure still needs to be visible somewhere."""
    if run.sync_error:
        return run.sync_error
    if run.refresh_error:
        return f"Token-Auffrischung fehlgeschlagen: {run.refresh_error}"
    return None


def job_status(job: SyncJob) -> JobStatus:
    """The Instagram sync job, context-neutral, for the /einstellungen automation section."""
    runs = tuple(
        JobRun(at=run.at, error=_run_error(run), summary=sync_summary(run.report))
        for run in reversed(job.runs)
    )
    return JobStatus(
        key="posts", label="Instagram-Abgleich", runs=runs, sync_action="/sync", streak=job.streak
    )


def _destination_label(d: Destination, multi_target: bool) -> str:
    """Same rule as delivery_label: the Instagram channel is never disambiguated by address."""
    if multi_target and d.sink != "instagram":
        return f"{sink_label(d.sink)} {d.address}"
    return sink_label(d.sink)


def outcome_line(entry: ReviewLogEntry, multi_target: bool) -> str:
    """'Freigegeben → Instagram, Telegram' / 'Abgelehnt' / 'Automatisch veröffentlicht → …'."""
    if entry.outcome == ReviewOutcome.REJECTED:
        return "Abgelehnt"
    verb = (
        "Freigegeben" if entry.outcome == ReviewOutcome.APPROVED else "Automatisch veröffentlicht"
    )
    targets = ", ".join(_destination_label(d, multi_target) for d in sorted(entry.targets))
    return f"{verb} → {targets}" if targets else verb


def instagram_hint(ch: InstagramChannel) -> str | None:
    """Why the Instagram checkbox on the compose form is disabled, or None when it isn't."""
    if not ch.connected:
        return "Instagram ist nicht verbunden."
    if not ch.can_publish:
        return "Instagram neu verbinden, um Veröffentlichen freizuschalten."
    if not ch.public_https:
        return (
            "PUBLIC_BASE_URL ist keine öffentliche https-Adresse – Instagram kann die Bilder "
            "nicht laden. Telegram geht trotzdem."
        )
    return None


def inbox_zero_line(stats: ReviewStats, now: datetime) -> str | None:
    """The Freigabe empty state's second line — how long, and whether it's a record.

    None whenever the log has no decision to measure from (empty_since is
    None): the "record" language only makes sense once at least one stretch
    has actually been measured.
    """
    if stats.empty_since is None:
        return None
    current = now - stats.empty_since
    if current < timedelta(seconds=60):
        return "Gerade erst geleert."
    current_text = format_duration(current, dative=True)
    if stats.longest_empty is None:
        return f"Seit {current_text} leer."
    if current >= stats.longest_empty:
        return f"Seit {current_text} leer – Rekord."
    return f"Seit {current_text} leer. Rekord: {format_duration(stats.longest_empty)}."


def reaction_line(stats: ReviewStats) -> str | None:
    """The Freigabe "Verlauf" section's reaction-time line, None without a measured reaction."""
    if stats.reactions == 0:
        return None
    assert stats.mean_reaction is not None  # reactions > 0 implies both are set
    if stats.reactions == 1:
        return f"Entschieden nach {format_duration(stats.mean_reaction, dative=True)}."
    assert stats.fastest_reaction is not None
    mean = format_duration(stats.mean_reaction, dative=True)
    fastest = format_duration(stats.fastest_reaction)
    return f"Im Schnitt nach {mean} entschieden, Rekord {fastest}."
