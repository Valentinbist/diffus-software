"""destinations and sources: sink/address on deliveries, source on tokens and posts

The connector no longer talks to exactly one Instagram account and one list of
Telegram chats. A delivery now targets a `Destination` (sink + address, e.g.
"telegram:-100...") instead of a bare Telegram chat_id, so a second sink can
deliver to the same address without colliding. Tokens are keyed by `source`
instead of a singleton `id=1` row, so a second source adapter can keep its own
credential. Posts carry their `source` so the id space can be shared safely
across sources later.

The 'telegram' / 'instagram' server defaults exist only to backfill existing
rows and are dropped again at the end of this migration, so a future adapter
that forgets to set sink/source fails loudly instead of silently defaulting.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # deliveries: chat_id -> sink + address, PK (post_id, chat_id) -> (post_id, sink, address).
    op.drop_constraint("deliveries_pkey", "deliveries", type_="primary")
    op.add_column(
        "deliveries",
        sa.Column("sink", sa.String(length=32), nullable=False, server_default="telegram"),
    )
    op.alter_column("deliveries", "chat_id", new_column_name="address")
    op.create_primary_key("deliveries_pkey", "deliveries", ["post_id", "sink", "address"])
    op.alter_column("deliveries", "sink", server_default=None)

    # tokens: singleton id=1 row -> keyed by source; ig_user_id -> external_user_id.
    op.add_column(
        "tokens",
        sa.Column("source", sa.String(length=32), nullable=False, server_default="instagram"),
    )
    op.drop_constraint("tokens_pkey", "tokens", type_="primary")
    op.drop_column("tokens", "id")  # also drops the sequence id owned, per Postgres OWNED BY
    op.create_primary_key("tokens_pkey", "tokens", ["source"])
    op.alter_column("tokens", "ig_user_id", new_column_name="external_user_id")
    op.alter_column("tokens", "source", server_default=None)

    # posts: every post now records which source adapter fetched it.
    op.add_column(
        "posts",
        sa.Column("source", sa.String(length=32), nullable=False, server_default="instagram"),
    )
    op.alter_column("posts", "source", server_default=None)

    # previews: untouched — still keyed by (post_id, media_index).


def downgrade() -> None:
    # posts: drop the source column.
    op.drop_column("posts", "source")

    # tokens: external_user_id -> ig_user_id; recreate `id` as a plain serial
    # PK (a fresh sequence, not the original one — any surviving row(s) get a
    # freshly assigned id, same as `save()` always writing id=1 before this
    # migration existed).
    op.alter_column("tokens", "external_user_id", new_column_name="ig_user_id")
    op.drop_constraint("tokens_pkey", "tokens", type_="primary")
    op.execute("CREATE SEQUENCE tokens_id_seq")
    op.add_column(
        "tokens",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("nextval('tokens_id_seq')"),
        ),
    )
    op.execute("ALTER SEQUENCE tokens_id_seq OWNED BY tokens.id")
    op.create_primary_key("tokens_pkey", "tokens", ["id"])
    op.drop_column("tokens", "source")

    # deliveries: address -> chat_id; PK (post_id, sink, address) -> (post_id, chat_id).
    # Fails with a uniqueness violation if two sinks ever delivered to the same
    # address for one post (e.g. telegram:x and signal:x) — the old two-column
    # PK has no room to keep both rows.
    op.drop_constraint("deliveries_pkey", "deliveries", type_="primary")
    op.alter_column("deliveries", "address", new_column_name="chat_id")
    op.drop_column("deliveries", "sink")
    op.create_primary_key("deliveries_pkey", "deliveries", ["post_id", "chat_id"])
