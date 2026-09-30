"""Track income payday expectations and actual receipt dates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104_budget_income_receipts"
down_revision: str | None = "0103_legal_test_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "budget_income_sources",
        sa.Column("usual_payday_day", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "budget_income_sources",
        sa.Column("recurring", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "budget_month_income",
        sa.Column("usual_payday_day", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "budget_month_income",
        sa.Column("recurring", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("budget_month_income", sa.Column("received_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("budget_month_income", "received_date")
    op.drop_column("budget_month_income", "recurring")
    op.drop_column("budget_month_income", "usual_payday_day")
    op.drop_column("budget_income_sources", "recurring")
    op.drop_column("budget_income_sources", "usual_payday_day")
