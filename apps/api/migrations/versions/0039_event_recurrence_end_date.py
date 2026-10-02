"""Add an inclusive calendar date for recurring event end conditions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_event_recurrence_end_date"
down_revision: str | None = "0038_household_adult"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("recurrence_end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("calendar_events", "recurrence_end_date")
