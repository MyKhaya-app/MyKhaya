"""Add the additive Budget fixed-actual component."""

import sqlalchemy as sa
from alembic import op

revision: str = "0089_budget_fixed_actual"
down_revision: str | None = "0088_support_disabled_by_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL preserves the meaning of rows created under the legacy
    # manual-versus-entries model. New snapshots receive the model default of
    # zero and therefore use fixed_actual + entries_actual.
    op.add_column(
        "budget_month_categories",
        sa.Column("fixed_actual", sa.Numeric(12, 2), nullable=True, server_default="0"),
    )

    # Rows without a legacy manual amount have an unambiguous fixed component
    # of zero. Initialise only those rows so entry totals become additive
    # without reinterpreting existing manually-entered actuals.
    op.execute(
        sa.text(
            "UPDATE budget_month_categories "
            "SET fixed_actual = 0 "
            "WHERE manual_actual IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("budget_month_categories", "fixed_actual")
