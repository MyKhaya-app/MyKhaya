"""Add reusable Budget items and historical month-item snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0085_budget_items"
down_revision: str | None = "0084_budget_share_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    item_type = postgresql.ENUM("fixed", "variable", name="budget_item_type")
    item_type.create(op.get_bind(), checkfirst=True)
    item_type_column = postgresql.ENUM(
        "fixed", "variable", name="budget_item_type", create_type=False
    )

    op.create_table(
        "budget_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("profile_id", sa.UUID(), sa.ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.UUID(), sa.ForeignKey("budget_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("item_type", item_type_column, nullable=False),
        sa.Column("default_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("recurring", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_items_profile_id", "budget_items", ["profile_id"])
    op.create_index("ix_budget_item_profile_active", "budget_items", ["profile_id", "archived_at"])
    op.create_index("ix_budget_item_category_active", "budget_items", ["category_id", "archived_at"])

    op.create_table(
        "budget_month_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("month_id", sa.UUID(), sa.ForeignKey("budget_months.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_item_id", sa.UUID(), sa.ForeignKey("budget_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_id", sa.UUID(), sa.ForeignKey("budget_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name_snapshot", sa.String(length=160), nullable=False),
        sa.Column("item_type_snapshot", item_type_column, nullable=False),
        sa.Column("planned_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("month_id", "budget_item_id", name="uq_budget_month_item"),
    )
    op.create_index("ix_budget_month_item_month_id", "budget_month_items", ["month_id"])
    op.create_index("ix_budget_month_item_budget_item_id", "budget_month_items", ["budget_item_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_month_item_budget_item_id", table_name="budget_month_items")
    op.drop_index("ix_budget_month_item_month_id", table_name="budget_month_items")
    op.drop_index("ix_budget_month_items_month_id", table_name="budget_month_items")
    op.drop_table("budget_month_items")
    op.drop_index("ix_budget_item_category_active", table_name="budget_items")
    op.drop_index("ix_budget_item_profile_active", table_name="budget_items")
    op.drop_index("ix_budget_items_profile_id", table_name="budget_items")
    op.drop_table("budget_items")
    sa.Enum(name="budget_item_type").drop(op.get_bind(), checkfirst=True)
