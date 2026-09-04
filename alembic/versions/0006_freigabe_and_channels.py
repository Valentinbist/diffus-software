"""freigabe and channels: channel_settings, post_drafts.targets/event_ref, ix_deliveries_status

Round 3 (Freigabe): nothing goes out until a human approves it, unless the
destination's own auto-publish switch says otherwise. `channel_settings` is
that switch, one row per `Destination` text form, defaulting to off (a
missing row means "not auto") — "Freigabe first" is the safe default, so
there is deliberately no backfill turning existing channels on.

`post_drafts.targets` mirrors what `PublishTargets` looked like when the
draft was submitted (JSONB: `{"instagram": bool, "destinations": [...]}`),
persisted so a REVIEW draft's checkboxes and a FAILED draft's retry both know
what to publish to without the caller re-supplying it — see
`PostDraft.submit_for_review`/`is_reviewable`. `post_drafts.event_ref` is
"calendar:<event id>" for a draft started from an event's "Post erstellen",
None for a standalone post; it is how `PublishDraft` finds the event to link
back to after publishing (`EventDirectory.link`).

`deliveries.status` gains the value "review" without a DDL change (it is a
plain VARCHAR, not a Postgres enum) — but the review queue and its nav badge
now query by status on every request, hence `ix_deliveries_status`.

The downgrade runs before 0005's status values are the only ones the
(rolled-back) application code understands, so "review" rows are neutralised
first: a queued delivery becomes SKIPPED (nothing was ever sent, same as a
never-approved one), a queued/failed draft becomes FAILED with an explanatory
error (its targets are lost with the column, so it can only be discarded, not
silently mis-published).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_settings",
        sa.Column("destination", sa.String(length=100), primary_key=True),
        sa.Column("auto_publish", sa.Boolean(), nullable=False),
    )

    op.add_column("post_drafts", sa.Column("targets", JSONB(), nullable=True))
    op.add_column("post_drafts", sa.Column("event_ref", sa.String(length=80), nullable=True))

    op.create_index("ix_deliveries_status", "deliveries", ["status"])


def downgrade() -> None:
    # Neutralise "review" rows before dropping the columns/index that make
    # them meaningful — a rolled-back app has no idea what REVIEW means.
    op.execute("UPDATE deliveries SET status = 'skipped' WHERE status = 'review'")
    op.execute(
        "UPDATE post_drafts SET status = 'failed', "
        "error = 'Downgrade von Freigabe (0006): Ziel-Auswahl ging verloren.' "
        "WHERE status = 'review'"
    )

    op.drop_index("ix_deliveries_status", table_name="deliveries")
    op.drop_column("post_drafts", "event_ref")
    op.drop_column("post_drafts", "targets")
    op.drop_table("channel_settings")
