"""Persist the user-owned Budget month-start setting."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080_budget_month_start"
down_revision: str | None = "0079_budget_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "budget_profiles",
        sa.Column("month_start_day", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_budget_profile_month_start_day",
        "budget_profiles",
        "month_start_day >= 1 AND month_start_day <= 28",
    )


def downgrade() -> None:
    op.drop_constraint("ck_budget_profile_month_start_day", "budget_profiles", type_="check")
    op.drop_column("budget_profiles", "month_start_day")
