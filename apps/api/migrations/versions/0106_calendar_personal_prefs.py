"""Add personal calendar settings and event attendance state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106_calendar_personal_prefs"
down_revision: str | None = "0105_colour_token_expansion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The two default-reminder toggles are server-default FALSE on purpose: ADD COLUMN backfills
    # every existing notification_preferences row with the server default, so a TRUE default
    # here would opt every existing user in to new Calendar notifications on deploy. They stay
    # off until the person turns them on in Calendar settings.
    op.add_column("calendar_event_members", sa.Column("attendance_status", sa.String(length=10), server_default="accepted", nullable=False))
    op.create_check_constraint("ck_calendar_event_member_attendance_status", "calendar_event_members", "attendance_status IN ('accepted', 'declined')")
    op.add_column("notification_preferences", sa.Column("default_event_reminder_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("notification_preferences", sa.Column("default_event_reminder_minutes", sa.Integer(), server_default="30", nullable=False))
    op.add_column("notification_preferences", sa.Column("all_day_reminder_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("notification_preferences", sa.Column("all_day_reminder_time", sa.Time(), server_default="09:00:00", nullable=False))
    op.add_column("notification_preferences", sa.Column("default_calendar_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_notification_preferences_default_calendar", "notification_preferences", "home_calendars", ["default_calendar_id"], ["id"], ondelete="SET NULL")
    op.add_column("notification_preferences", sa.Column("week_starts_on", sa.String(length=9), server_default="monday", nullable=False))
    op.add_column("notification_preferences", sa.Column("show_declined_events", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_constraint("ck_calendar_event_member_attendance_status", "calendar_event_members", type_="check")
    op.drop_column("calendar_event_members", "attendance_status")
    op.drop_constraint("fk_notification_preferences_default_calendar", "notification_preferences", type_="foreignkey")
    for name in ("show_declined_events", "week_starts_on", "default_calendar_id", "all_day_reminder_time", "all_day_reminder_enabled", "default_event_reminder_minutes", "default_event_reminder_enabled"):
        op.drop_column("notification_preferences", name)
