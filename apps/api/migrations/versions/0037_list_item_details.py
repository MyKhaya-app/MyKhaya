"""Lists V1: add an optional icon to household_lists, and optional
quantity/note/assignment/completion-metadata columns to
household_list_items, plus an index for efficient remaining/completed
counts.

Purely additive — every new column is nullable, so existing rows (including
those Meal Plans' "Add ingredients to list" already created) remain valid
without backfill. See docs/architecture/lists.md.

Revision ID: 0037_list_item_details
Revises: 0036_household_lists
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_list_item_details"
down_revision: str | None = "0036_household_lists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("household_lists", sa.Column("icon", sa.String(20)))
    op.add_column("household_list_items", sa.Column("quantity", sa.String(40)))
    op.add_column("household_list_items", sa.Column("note", sa.String(500)))
    op.add_column(
        "household_list_items",
        sa.Column(
            "assigned_member_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
    )
    op.add_column("household_list_items", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "household_list_items",
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index(
        "ix_household_list_item_list_checked", "household_list_items", ["list_id", "is_checked"]
    )


def downgrade() -> None:
    op.drop_index("ix_household_list_item_list_checked", table_name="household_list_items")
    op.drop_column("household_list_items", "completed_by")
    op.drop_column("household_list_items", "completed_at")
    op.drop_column("household_list_items", "assigned_member_id")
    op.drop_column("household_list_items", "note")
    op.drop_column("household_list_items", "quantity")
    op.drop_column("household_lists", "icon")
