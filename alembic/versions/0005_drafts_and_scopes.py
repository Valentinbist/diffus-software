"""drafts and scopes: post_drafts + post_draft_media, tokens.scopes, an index for linked_events

A wizard that composes a post is a two-step flow — upload images, then choose
targets and publish — so the uploaded images (already normalised to JPEG) and
the caption have to survive between the two requests. `post_drafts` is that
storage; `post_draft_media` holds one row per uploaded image, ordered by
`media_index`. Instagram does not accept image bytes directly: `POST
.../media` takes an `image_url` it fetches itself, so a draft's images must
be reachable at a public URL for the few seconds it takes Instagram to fetch
them. `public_key` is the per-draft secret in that URL
(`GET /media/drafts/{id}/{index}?key=...`) — the route is unauthenticated
(Meta can't carry our Basic auth credentials), so the key is what keeps a
draft's images from being guessable.

`post_drafts.post_id` carries no foreign key on purpose: the `posts` row is
only created once publishing succeeds, well after the draft exists, and a
draft is kept afterwards as an audit trail of what was uploaded and when —
outliving the row it produced, not depending on it.

`ix_calendar_event_posts_post_id` speeds up `GetLinkedEvents.for_posts`,
which looks events up by a list of post ids (the reverse of the table's
primary key order, which starts with `event_id`).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tokens", sa.Column("scopes", sa.Text(), nullable=True))

    op.create_table(
        "post_drafts",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        # No foreign key: the post it eventually produces is created at
        # publish time, well after the draft — see the module docstring.
        sa.Column("post_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "post_draft_media",
        sa.Column(
            "draft_id",
            sa.String(length=32),
            sa.ForeignKey("post_drafts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_index", sa.Integer(), primary_key=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )

    op.create_index(
        "ix_calendar_event_posts_post_id", "calendar_event_posts", ["post_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_event_posts_post_id", table_name="calendar_event_posts")
    op.drop_table("post_draft_media")
    op.drop_table("post_drafts")
    op.drop_column("tokens", "scopes")
