"""Add Wishlist.home_visible: wishlists default to Private and only become
visible to same-Home members (via Capability.wishlists_view) when the owner
explicitly opts in. Fully additive — one nullable-free boolean column with a
false server default, plus a supporting index for the "home_id + visible"
list-query shape (mykhaya.routers.wishlists.list_wishlists).

Existing rows (there are none in production yet, but this is written as if
there were) all backfill to false — exactly matching "must not become
suddenly Home-visible" for anything created before this migration ran.

Revision ID: 0042_wishlist_home_visibility
Revises: 0041_wishlists
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_wishlist_home_visibility"
down_revision: str | None = "0041_wishlists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wishlists",
        sa.Column("home_visible", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_wishlist_home_visible", "wishlists", ["home_id", "home_visible"]
    )


def downgrade() -> None:
    op.drop_index("ix_wishlist_home_visible", table_name="wishlists")
    op.drop_column("wishlists", "home_visible")
