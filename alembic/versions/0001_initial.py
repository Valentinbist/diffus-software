"""initial schema: tokens, posts, deliveries

Revision ID: 0001
Revises:
Create Date: 2026-08-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("ig_user_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=False),
        sa.Column("media", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "deliveries",
        sa.Column("post_id", sa.String(length=64), sa.ForeignKey("posts.id"), primary_key=True),
        sa.Column("chat_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_table("posts")
    op.drop_table("tokens")
