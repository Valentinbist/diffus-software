"""queue timestamps: deliveries.queued_at, post_drafts.submitted_at, review_log.queued_at

Round 7 ("fun layer"): the Freigabe page's reaction-time and inbox-zero lines
("Im Schnitt nach 12 Minuten entschieden", "Seit 3 Stunden leer") need to
know when something *entered* the queue, not just when it left — and
`review_log` (migration 0007) only ever recorded the latter (`at`). These
three nullable columns are that missing half: `deliveries.queued_at` and
`post_drafts.submitted_at` are stamped by `Delivery.queue_for_review` and
`PostDraft.submit_for_review` respectively (see domain/entities.py);
`review_log.queued_at` copies whichever of those applies when the decision
is logged (`ApprovePostDeliveries`/`RejectPostDeliveries`/`ApproveDraft`/
`RejectDraft` in application/review.py and drafts.py) and stays None for an
AUTO entry, which was never queued for a human at all. `ReviewStats`
(domain/stats.py) is what turns the log's `(queued_at, at)` pairs into a
reaction time and the queue's empty stretches.

All three are nullable, so nothing older than this migration claims to know
a queued/submitted time it never recorded.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deliveries", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "post_drafts", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("review_log", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("review_log", "queued_at")
    op.drop_column("post_drafts", "submitted_at")
    op.drop_column("deliveries", "queued_at")
