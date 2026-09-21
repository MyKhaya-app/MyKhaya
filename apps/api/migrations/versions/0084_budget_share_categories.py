"""Persist the categories selected for a category-level Budget share."""

import sqlalchemy as sa
from alembic import op

revision: str = "0084_budget_share_categories"
down_revision: str | None = "0083_budget_notes_default_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_partner_shares", sa.Column("category_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("budget_partner_shares", "category_ids")
