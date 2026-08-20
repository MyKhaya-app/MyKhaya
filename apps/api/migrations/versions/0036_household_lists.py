"""Add Household Lists: MyKhaya's one shared-list primitive (groceries,
packing, to-dos, and Meal Plans' "Add ingredients to list" destination).

See docs/architecture/meal-plans.md and mykhaya.routers.lists. Reuses the
existing FeatureKey.shopping feature-flag row and the pre-declared
"lists.enabled" entitlement rather than adding either.

Revision ID: 0036_household_lists
Revises: 0035_meal_plans
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_household_lists"
down_revision: str | None = "0035_meal_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household_lists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_household_list_name_nonempty"),
    )
    op.create_index("ix_household_lists_group_id", "household_lists", ["group_id"])
    op.create_index(
        "ix_household_list_group_active", "household_lists", ["group_id", "deleted_at"]
    )

    op.create_table(
        "household_list_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "list_id", sa.Uuid(), sa.ForeignKey("household_lists.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("is_checked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.CheckConstraint("char_length(text) >= 1", name="ck_household_list_item_text_nonempty"),
    )
    op.create_index("ix_household_list_items_list_id", "household_list_items", ["list_id"])
    op.create_index(
        "ix_household_list_item_list_position", "household_list_items", ["list_id", "position"]
    )


def downgrade() -> None:
    op.drop_index("ix_household_list_item_list_position", table_name="household_list_items")
    op.drop_index("ix_household_list_items_list_id", table_name="household_list_items")
    op.drop_table("household_list_items")

    op.drop_index("ix_household_list_group_active", table_name="household_lists")
    op.drop_index("ix_household_lists_group_id", table_name="household_lists")
    op.drop_table("household_lists")
