"""calendar: sub-calendars, events, event<->sub-calendar links, event<->post links

The calendar bounded context syncs a shared external calendar
(kalender.digital) and lets a post get linked to an event. Events are
persisted locally — not just read through on demand — because a link needs a
stable local row to attach to: when an event disappears from the upstream
calendar, `EventRepository.mark_removed` stamps `removed_at` on its row
instead of deleting it, so any existing links survive and the calendar UI can
still show what the (now-gone) event was linked to.

`calendar_event_posts.post_id` carries no foreign key: the post lives in the
crossposting context's `posts` table, and one context's schema never
references another's (see docs/architecture.md, Bounded contexts). The
column is plain text; the crossposting side of a link is validated by the
application layer through the `PostCatalog` port instead.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_sub_calendars",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("who", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("whole_day", sa.Boolean(), nullable=False),
        sa.Column("series_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])

    op.create_table(
        "calendar_event_sub_calendars",
        sa.Column(
            "event_id",
            sa.String(length=64),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sub_calendar_id",
            sa.BigInteger(),
            sa.ForeignKey("calendar_sub_calendars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_calendar_event_sub_calendars_sub_calendar_id",
        "calendar_event_sub_calendars",
        ["sub_calendar_id"],
    )

    op.create_table(
        "calendar_event_posts",
        sa.Column(
            "event_id",
            sa.String(length=64),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # No foreign key: post_id belongs to the crossposting context's posts
        # table (see the module docstring).
        sa.Column("post_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("calendar_event_posts")
    op.drop_index(
        "ix_calendar_event_sub_calendars_sub_calendar_id",
        table_name="calendar_event_sub_calendars",
    )
    op.drop_table("calendar_event_sub_calendars")
    op.drop_index("ix_calendar_events_starts_at", table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_table("calendar_sub_calendars")
