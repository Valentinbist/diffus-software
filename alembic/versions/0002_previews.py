"""previews: a stored still image per post media item

The UI used to hotlink Instagram's CDN, whose URLs expire. The sync now keeps a
copy of each still image while the link is fresh and serves it itself.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "previews",
        sa.Column("post_id", sa.String(length=64), sa.ForeignKey("posts.id"), primary_key=True),
        sa.Column("media_index", sa.Integer(), primary_key=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("previews")
