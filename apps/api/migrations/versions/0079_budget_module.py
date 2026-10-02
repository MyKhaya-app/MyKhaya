"""Add the disabled-by-default personal Budget foundation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0079_budget_module"
down_revision: str | None = "0078_consumer_mfa_preference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # FeatureKey is a PostgreSQL enum. The absent FeatureFlag row is
    # intentional: features.py fails closed, so Budget remains globally off
    # until a platform operator explicitly promotes it.
    # PostgreSQL does not allow a newly-added enum value to be used until the
    # transaction that adds it has committed. Alembic runs the whole upgrade
    # chain transactionally, so commit only this enum DDL before later
    # migrations insert the Budget feature flag row. The schema DDL below and
    # all subsequent migration work remain transactional.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE feature_key ADD VALUE IF NOT EXISTS 'budget'")
    budget_actual_source = postgresql.ENUM(
        "manual", "entries", name="budget_actual_source", create_type=False
    )
    budget_sharing_level = postgresql.ENUM(
        "summary", "categories", "full", name="budget_sharing_level", create_type=False
    )
    postgresql.ENUM("manual", "entries", name="budget_actual_source").create(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("summary", "categories", "full", name="budget_sharing_level").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "budget_profiles",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(3), server_default="GBP", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("owner_user_id"),
    )
    op.create_index("ix_budget_profiles_owner_user_id", "budget_profiles", ["owner_user_id"])
    op.create_table(
        "budget_months",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("profile_id", sa.UUID(), sa.ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("profile_id", "year", "month", name="uq_budget_month"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_budget_month_valid"),
    )
    op.create_index("ix_budget_months_profile_id", "budget_months", ["profile_id"])
    op.create_table(
        "budget_categories",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("profile_id", sa.UUID(), sa.ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("profile_id", "name", name="uq_budget_category_name"),
    )
    op.create_index("ix_budget_categories_profile_id", "budget_categories", ["profile_id"])
    op.create_index("ix_budget_category_profile_active", "budget_categories", ["profile_id", "archived_at"])
    op.create_table(
        "budget_income_sources",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("profile_id", sa.UUID(), sa.ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("profile_id", "name", name="uq_budget_income_source_name"),
    )
    op.create_index("ix_budget_income_sources_profile_id", "budget_income_sources", ["profile_id"])
    op.create_index("ix_budget_income_source_profile_active", "budget_income_sources", ["profile_id", "archived_at"])
    op.create_table(
        "budget_month_categories",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("month_id", sa.UUID(), sa.ForeignKey("budget_months.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.UUID(), sa.ForeignKey("budget_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_name", sa.String(100), nullable=False),
        sa.Column("planned_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("actual_source", budget_actual_source, server_default="manual", nullable=False),
        sa.Column("manual_actual", sa.Numeric(12, 2)),
        sa.UniqueConstraint("month_id", "category_id", name="uq_budget_month_category"),
    )
    op.create_index("ix_budget_month_categories_month_id", "budget_month_categories", ["month_id"])
    op.create_index("ix_budget_month_categories_category_id", "budget_month_categories", ["category_id"])
    op.create_table(
        "budget_month_income",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("month_id", sa.UUID(), sa.ForeignKey("budget_months.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.UUID(), sa.ForeignKey("budget_income_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("expected_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("received_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.UniqueConstraint("month_id", "source_id", name="uq_budget_month_income"),
    )
    op.create_index("ix_budget_month_income_month_id", "budget_month_income", ["month_id"])
    op.create_index("ix_budget_month_income_source_id", "budget_month_income", ["source_id"])
    op.create_table(
        "budget_spending_entries",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("month_category_id", sa.UUID(), sa.ForeignKey("budget_month_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_budget_spending_entries_month_category_id", "budget_spending_entries", ["month_category_id"])
    op.create_table(
        "budget_partner_shares",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("profile_id", sa.UUID(), sa.ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("partner_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", budget_sharing_level, server_default="summary", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("profile_id", "partner_user_id", name="uq_budget_partner_share"),
    )
    op.create_index("ix_budget_partner_shares_profile_id", "budget_partner_shares", ["profile_id"])
    op.create_index("ix_budget_partner_shares_partner_user_id", "budget_partner_shares", ["partner_user_id"])


def downgrade() -> None:
    op.drop_table("budget_partner_shares")
    op.drop_table("budget_spending_entries")
    op.drop_table("budget_month_income")
    op.drop_table("budget_month_categories")
    op.drop_table("budget_income_sources")
    op.drop_table("budget_categories")
    op.drop_table("budget_months")
    op.drop_table("budget_profiles")
    sa.Enum(name="budget_sharing_level").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="budget_actual_source").drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values cannot be removed safely. The feature_key value
    # remains harmless and the next migration can continue from this state.
