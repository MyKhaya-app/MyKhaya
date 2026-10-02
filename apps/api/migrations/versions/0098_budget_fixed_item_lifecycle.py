"""Add Budget fixed-item end date, item notes, and spending-entry payment link.

Additive only: every new column is nullable and every existing row keeps its
current behaviour (ends_on/notes null = unchanged item; budget_month_item_id
null = unlinked entry, same as today).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0098_budget_fixed_item_lifecycle"
down_revision: str | None = "0097_vehicle_photos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("budget_items", sa.Column("ends_on", sa.Date(), nullable=True))
    op.add_column("budget_items", sa.Column("notes", sa.String(length=1000), nullable=True))
    op.add_column(
        "budget_spending_entries",
        sa.Column(
            "budget_month_item_id",
            sa.UUID(),
            sa.ForeignKey("budget_month_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_budget_spending_entry_budget_month_item_id",
        "budget_spending_entries",
        ["budget_month_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_budget_spending_entry_budget_month_item_id",
        table_name="budget_spending_entries",
    )
    op.drop_column("budget_spending_entries", "budget_month_item_id")
    op.drop_column("budget_items", "notes")
    op.drop_column("budget_items", "ends_on")
