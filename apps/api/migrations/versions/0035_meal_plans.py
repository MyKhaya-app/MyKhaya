"""Add the Meal Plans module (Family-only): a household meal library, its
ingredients, planned meal entries, and who's eating.

See docs/architecture/meal-plans.md and mykhaya.routers.meal_plans. Two new
enum types (meal_type, meal_slot) — meal_slot is deliberately narrower than
meal_type (breakfast/lunch/dinner only; the planner has exactly three rows a
day, but a saved "dessert" or "snack" Meal can still be planned into any of
them).

Revision ID: 0035_meal_plans
Revises: 0034_stripe_billing_diagnostics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_meal_plans"
down_revision: str | None = "0034_stripe_billing_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

meal_type = postgresql.ENUM(
    "breakfast", "lunch", "dinner", "snack", "dessert", "other", name="meal_type", create_type=False
)
meal_slot = postgresql.ENUM("breakfast", "lunch", "dinner", name="meal_slot", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "breakfast", "lunch", "dinner", "snack", "dessert", "other", name="meal_type"
    ).create(bind)
    postgresql.ENUM("breakfast", "lunch", "dinner", name="meal_slot").create(bind)

    op.create_table(
        "meals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(2000)),
        sa.Column("image_url", sa.String(2000)),
        sa.Column("meal_type", meal_type, nullable=False, server_default="dinner"),
        sa.Column("prep_minutes", sa.Integer()),
        sa.Column("cook_minutes", sa.Integer()),
        sa.Column("servings", sa.Integer()),
        sa.Column("instructions", sa.String(8000)),
        sa.Column("is_favourite", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_url", sa.String(2000)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_meal_name_nonempty"),
    )
    op.create_index("ix_meals_group_id", "meals", ["group_id"])
    op.create_index("ix_meal_group_type", "meals", ["group_id", "meal_type"])
    op.create_index("ix_meal_group_active", "meals", ["group_id", "deleted_at"])

    op.create_table(
        "meal_ingredients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("meal_id", sa.Uuid(), sa.ForeignKey("meals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.String(40)),
        sa.Column("unit", sa.String(40)),
        sa.Column("text", sa.String(200), nullable=False),
    )
    op.create_index("ix_meal_ingredients_meal_id", "meal_ingredients", ["meal_id"])
    op.create_index("ix_meal_ingredient_meal_position", "meal_ingredients", ["meal_id", "position"])

    op.create_table(
        "meal_plan_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meal_id", sa.Uuid(), sa.ForeignKey("meals.id", ondelete="SET NULL")),
        sa.Column("quick_meal_name", sa.String(160)),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("meal_slot", meal_slot, nullable=False),
        sa.Column("time", sa.Time()),
        sa.Column("cook_member_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("makes_leftovers", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(meal_id IS NOT NULL) OR (quick_meal_name IS NOT NULL)",
            name="ck_meal_plan_entry_has_meal",
        ),
    )
    op.create_index("ix_meal_plan_entries_group_id", "meal_plan_entries", ["group_id"])
    op.create_index("ix_meal_plan_entries_meal_id", "meal_plan_entries", ["meal_id"])
    op.create_index("ix_meal_plan_entry_group_date", "meal_plan_entries", ["group_id", "date"])
    op.create_index("ix_meal_plan_entry_group_active", "meal_plan_entries", ["group_id", "deleted_at"])

    op.create_table(
        "meal_plan_participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "meal_plan_entry_id",
            sa.Uuid(),
            sa.ForeignKey("meal_plan_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("meal_plan_entry_id", "user_id", name="uq_meal_plan_participant"),
    )
    op.create_index(
        "ix_meal_plan_participants_meal_plan_entry_id",
        "meal_plan_participants",
        ["meal_plan_entry_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meal_plan_participants_meal_plan_entry_id", table_name="meal_plan_participants"
    )
    op.drop_table("meal_plan_participants")

    op.drop_index("ix_meal_plan_entry_group_active", table_name="meal_plan_entries")
    op.drop_index("ix_meal_plan_entry_group_date", table_name="meal_plan_entries")
    op.drop_index("ix_meal_plan_entries_meal_id", table_name="meal_plan_entries")
    op.drop_index("ix_meal_plan_entries_group_id", table_name="meal_plan_entries")
    op.drop_table("meal_plan_entries")

    op.drop_index("ix_meal_ingredient_meal_position", table_name="meal_ingredients")
    op.drop_index("ix_meal_ingredients_meal_id", table_name="meal_ingredients")
    op.drop_table("meal_ingredients")

    op.drop_index("ix_meal_group_active", table_name="meals")
    op.drop_index("ix_meal_group_type", table_name="meals")
    op.drop_index("ix_meals_group_id", table_name="meals")
    op.drop_table("meals")

    bind = op.get_bind()
    postgresql.ENUM(name="meal_slot").drop(bind)
    postgresql.ENUM(name="meal_type").drop(bind)
