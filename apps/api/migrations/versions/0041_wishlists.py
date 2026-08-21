"""Add Wishlists V1: per-person wishlists with items, reservations, and
household/cross-Home/guest sharing.

Additive only — five new tables, four new enum types, no changes to any
existing table.

Reservation state is deliberately not a column on wishlist_items: a row in
`wishlist_item_reservations` (unique on `wishlist_item_id`) *is* the
"reserved"/"bought" state; its absence *is* "available". The item's owner is
never joined against this table in application code (see
mykhaya.routers.wishlists) — that is the enforcement point for the
"owner must never learn an item was reserved" rule, not this migration.

`wishlist_shares` stores no separate token column: a guest share link's
token is the HMAC-signed encoding of the share row's own `id`
(mykhaya.security.derived_token), the same mechanism invitation links
already use, so there is nothing here to index for token lookup beyond the
primary key.

Revision ID: 0041_wishlists
Revises: 0040_status_incident_timeline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_wishlists"
down_revision: str | None = "0040_status_incident_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

wishlist_occasion = postgresql.ENUM(
    "birthday",
    "christmas",
    "general",
    "other",
    name="wishlist_occasion",
    create_type=False,
)
wishlist_reservation_status = postgresql.ENUM(
    "reserved",
    "bought",
    name="wishlist_reservation_status",
    create_type=False,
)
wishlist_reservation_actor_type = postgresql.ENUM(
    "member",
    "guest",
    name="wishlist_reservation_actor_type",
    create_type=False,
)
wishlist_share_type = postgresql.ENUM(
    "mykhaya_user",
    "guest",
    name="wishlist_share_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    wishlist_occasion.create(bind)
    wishlist_reservation_status.create(bind)
    wishlist_reservation_actor_type.create(bind)
    wishlist_share_type.create(bind)

    op.create_table(
        "wishlists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "home_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("occasion", wishlist_occasion, nullable=False),
        sa.Column("occasion_date", sa.Date()),
        sa.Column("description", sa.String(1000)),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_wishlist_title_nonempty"),
    )
    op.create_index("ix_wishlists_home_id", "wishlists", ["home_id"])
    op.create_index("ix_wishlists_owner_user_id", "wishlists", ["owner_user_id"])
    op.create_index("ix_wishlist_home_owner", "wishlists", ["home_id", "owner_user_id"])
    op.create_index("ix_wishlist_home_active", "wishlists", ["home_id", "deleted_at"])

    op.create_table(
        "wishlist_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "wishlist_id",
            sa.Uuid(),
            sa.ForeignKey("wishlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.String(2000)),
        sa.Column("price", sa.Numeric(10, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("note", sa.String(500)),
        sa.Column("image_url", sa.String(2000)),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_wishlist_item_name_nonempty"),
        sa.CheckConstraint("quantity >= 1", name="ck_wishlist_item_quantity_positive"),
    )
    op.create_index("ix_wishlist_items_wishlist_id", "wishlist_items", ["wishlist_id"])
    op.create_index(
        "ix_wishlist_item_wishlist_position", "wishlist_items", ["wishlist_id", "sort_order"]
    )

    op.create_table(
        "wishlist_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "wishlist_id",
            sa.Uuid(),
            sa.ForeignKey("wishlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_name", sa.String(100), nullable=False),
        sa.Column("recipient_email", sa.String(320)),
        sa.Column(
            "recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("share_type", wishlist_share_type, nullable=False),
        sa.Column("pin_hash", sa.Text()),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_wishlist_shares_wishlist_id", "wishlist_shares", ["wishlist_id"])
    op.create_index(
        "ix_wishlist_share_wishlist_active", "wishlist_shares", ["wishlist_id", "revoked_at"]
    )
    op.create_index(
        "ix_wishlist_share_recipient_user", "wishlist_shares", ["recipient_user_id"]
    )

    op.create_table(
        "wishlist_guest_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "share_id",
            sa.Uuid(),
            sa.ForeignKey("wishlist_shares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_wishlist_guest_session_share", "wishlist_guest_sessions", ["share_id"]
    )
    op.create_index(
        "ix_wishlist_guest_sessions_token_hash", "wishlist_guest_sessions", ["token_hash"]
    )

    op.create_table(
        "wishlist_item_reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "wishlist_item_id",
            sa.Uuid(),
            sa.ForeignKey("wishlist_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", wishlist_reservation_status, nullable=False),
        sa.Column("actor_type", wishlist_reservation_actor_type, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "actor_share_id", sa.Uuid(), sa.ForeignKey("wishlist_shares.id", ondelete="SET NULL")
        ),
        sa.Column("buyer_display_name", sa.String(100), nullable=False),
        sa.UniqueConstraint("wishlist_item_id", name="uq_wishlist_item_reservation"),
    )
    op.create_index(
        "ix_wishlist_item_reservations_wishlist_item_id",
        "wishlist_item_reservations",
        ["wishlist_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wishlist_item_reservations_wishlist_item_id",
        table_name="wishlist_item_reservations",
    )
    op.drop_table("wishlist_item_reservations")

    op.drop_index("ix_wishlist_guest_sessions_token_hash", table_name="wishlist_guest_sessions")
    op.drop_index("ix_wishlist_guest_session_share", table_name="wishlist_guest_sessions")
    op.drop_table("wishlist_guest_sessions")

    op.drop_index("ix_wishlist_share_recipient_user", table_name="wishlist_shares")
    op.drop_index("ix_wishlist_share_wishlist_active", table_name="wishlist_shares")
    op.drop_index("ix_wishlist_shares_wishlist_id", table_name="wishlist_shares")
    op.drop_table("wishlist_shares")

    op.drop_index("ix_wishlist_item_wishlist_position", table_name="wishlist_items")
    op.drop_index("ix_wishlist_items_wishlist_id", table_name="wishlist_items")
    op.drop_table("wishlist_items")

    op.drop_index("ix_wishlist_home_active", table_name="wishlists")
    op.drop_index("ix_wishlist_home_owner", table_name="wishlists")
    op.drop_index("ix_wishlists_owner_user_id", table_name="wishlists")
    op.drop_index("ix_wishlists_home_id", table_name="wishlists")
    op.drop_table("wishlists")

    bind = op.get_bind()
    postgresql.ENUM(name="wishlist_share_type").drop(bind)
    postgresql.ENUM(name="wishlist_reservation_actor_type").drop(bind)
    postgresql.ENUM(name="wishlist_reservation_status").drop(bind)
    postgresql.ENUM(name="wishlist_occasion").drop(bind)
