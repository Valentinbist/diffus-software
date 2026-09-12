"""review log: append-only history of Freigabe decisions and auto-publishes

Round 5 ("I would like to see a history"): the Freigabe queue only ever
shows what is still open, so once a draft or a post's deliveries are
approved, rejected, or auto-published, there is no record of it anywhere.
`review_log` is that record — one row per human decision (`ApprovePostDeliveries`,
`RejectPostDeliveries`, `ApproveDraft`, `RejectDraft`) or auto-publish
(`SubmitDraft`'s all-auto path, `SyncPosts`'s per-post auto deliveries) — see
`ReviewLogEntry` and docs/architecture.md, "Freigabe (approval queue)".

`post_id` carries no foreign key, the same reasoning as `post_drafts.post_id`
(migration `0005`): a rejected draft never becomes a post, so the column has
to represent "never was one", not just "not yet". `targets` is a JSONB list
of `Destination` text forms (`["telegram:-100…"]`), `()` for a rejected
draft. `ix_review_log_at` is what the Freigabe page's "Verlauf" section
(newest first, `recent(limit=30)`) queries against.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_log",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("post_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("targets", JSONB(), nullable=False),
    )
    op.create_index("ix_review_log_at", "review_log", ["at"])


def downgrade() -> None:
    op.drop_index("ix_review_log_at", table_name="review_log")
    op.drop_table("review_log")
