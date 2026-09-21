"""Add optional notes to Budget spending entries."""

import sqlalchemy as sa
from alembic import op

revision: str = "0086_budget_spending_entry_notes"
down_revision: str | None = "0085_budget_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_spending_entries", sa.Column("note", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("budget_spending_entries", "note")
