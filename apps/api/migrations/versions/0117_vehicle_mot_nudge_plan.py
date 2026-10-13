"""Driveway MOT nudges: the owner's MOT reminder plan on each vehicle.

Additive only: one nullable JSON column on ``vehicles``. No existing column,
value, constraint or index changes; no data is written. The reminders a plan
creates are ordinary ``reminders`` rows (see mykhaya.driveway_mot_nudges), so
downgrade drops only the plan itself; those reminders stay as normal one-off
Driveway reminders."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0117_vehicle_mot_nudge_plan"
down_revision: str | None = "0116_vehicle_mot_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("mot_nudge_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "mot_nudge_plan")
