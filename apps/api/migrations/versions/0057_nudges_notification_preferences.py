"""Add Nudges evening notification preferences.

Revision ID: 0057_nudges_prefs
Revises: 0056_nudges_todos
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057_nudges_prefs"
down_revision: str | None = "0056_nudges_todos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_preferences", sa.Column("nudges_evening_cleanup_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("notification_preferences", sa.Column("nudges_evening_time", sa.Time(), nullable=False, server_default="20:30:00"))
    op.add_column("notification_preferences", sa.Column("nudges_day_complete_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("notification_preferences", "nudges_day_complete_enabled")
    op.drop_column("notification_preferences", "nudges_evening_time")
    op.drop_column("notification_preferences", "nudges_evening_cleanup_enabled")
