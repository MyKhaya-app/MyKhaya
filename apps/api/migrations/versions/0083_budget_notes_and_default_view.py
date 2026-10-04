"""Add category notes and the persisted Budget default view."""

import sqlalchemy as sa
from alembic import op

revision: str = "0083_budget_notes_default_view"
down_revision: str | None = "0082_budget_platform_rollout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_profiles", sa.Column("default_view", sa.String(length=20), nullable=False, server_default="personal"))
    op.add_column("budget_month_categories", sa.Column("note", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("budget_month_categories", "note")
    op.drop_column("budget_profiles", "default_view")
