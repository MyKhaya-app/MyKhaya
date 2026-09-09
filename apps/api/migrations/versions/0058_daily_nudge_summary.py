"""Add Daily Nudge Summary notification preferences.

Separate from Daily Briefing (daily_briefing_enabled/briefing_time, untouched
here) and from the existing evening Nudges preferences (nudges_evening_*,
also untouched) — this is the new user-configurable *morning* digest of
today's outstanding Routines/Reminders/To-dos. Default ON at 07:30 for both
new and existing users, per explicit product decision (server_default covers
both: new rows get it from the column default, existing rows are backfilled
by the DDL's server_default at add-column time).

Revision ID: 0058_daily_nudge_summary
Revises: 0057_nudges_prefs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_daily_nudge_summary"
down_revision: str | None = "0057_nudges_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column(
            "daily_nudge_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "notification_preferences",
        sa.Column(
            "daily_nudge_summary_time",
            sa.Time(),
            nullable=False,
            server_default="07:30:00",
        ),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "daily_nudge_summary_time")
    op.drop_column("notification_preferences", "daily_nudge_summary_enabled")
