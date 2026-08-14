"""Add an explicit daily/weekly recurrence unit for routines."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_daily_routine_recurrence"
down_revision: str | None = "0025_scheduler_occurrence_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "household_routines",
        sa.Column("repeat_unit", sa.String(length=10), nullable=False, server_default="weekly"),
    )
    op.create_check_constraint(
        "ck_routine_repeat_unit",
        "household_routines",
        "repeat_unit IN ('daily', 'weekly')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_routine_repeat_unit", "household_routines", type_="check")
    op.drop_column("household_routines", "repeat_unit")
