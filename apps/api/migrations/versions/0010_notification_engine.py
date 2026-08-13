"""Add the Notification Engine: push subscriptions, in-app notifications, delivery
records, preferences, household routines, platform push (VAPID) settings, and
override-only notification templates. Also adds per-user timezone/birthday columns to
users and child_profiles.

This is the foundation for the Communications milestone — see
docs/architecture/notification-engine.md. All tables are additive; no existing data is
touched. The "notifications" feature flag (already seeded, default disabled, in
migration 0004) gates the whole surface until Platform Admin turns it on.

Revision ID: 0010_notification_engine
Revises: 0009_platform_smtp_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_notification_engine"
down_revision: str | None = "0009_platform_smtp_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    notification_channel = postgresql.ENUM(
        "email", "push", "in_app", name="notification_channel", create_type=False
    )
    notification_delivery_status = postgresql.ENUM(
        "queued", "sent", "failed", "cancelled", name="notification_delivery_status", create_type=False
    )
    lock_screen_preview_level = postgresql.ENUM(
        "full", "title_only", "hidden", name="lock_screen_preview_level", create_type=False
    )
    briefing_days = postgresql.ENUM("daily", "weekdays", name="briefing_days", create_type=False)
    routine_reminder_timing = postgresql.ENUM(
        "evening_before", "same_day", "both", name="routine_reminder_timing", create_type=False
    )
    notification_template_channel = postgresql.ENUM(
        "email", "push", "in_app", name="notification_template_channel", create_type=False
    )
    for enum in (
        notification_channel,
        notification_delivery_status,
        lock_screen_preview_level,
        briefing_days,
        routine_reminder_timing,
        notification_template_channel,
    ):
        enum.create(op.get_bind())

    op.add_column("users", sa.Column("timezone", sa.String(100)))
    op.add_column("users", sa.Column("birth_month", sa.Integer()))
    op.add_column("users", sa.Column("birth_day", sa.Integer()))
    op.add_column("users", sa.Column("birth_year", sa.Integer()))
    op.add_column("child_profiles", sa.Column("birth_month", sa.Integer()))
    op.add_column("child_profiles", sa.Column("birth_day", sa.Integer()))
    op.add_column("child_profiles", sa.Column("birth_year", sa.Integer()))
    op.add_column(
        "child_profiles",
        sa.Column("birthday_visible", sa.Boolean(), server_default="false", nullable=False),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh_key", sa.String(255), nullable=False),
        sa.Column("auth_key", sa.String(255), nullable=False),
        sa.Column("device_label", sa.String(120)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_reason", sa.String(200)),
        *timestamps(),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_index(
        "ix_push_subscriptions_user", "push_subscriptions", ["user_id", "disabled_at"]
    )

    op.create_table(
        "notifications",
        sa.Column(
            "recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="SET NULL")),
        sa.Column("notification_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("related_entity_type", sa.String(50)),
        sa.Column("related_entity_id", sa.Uuid()),
        sa.Column("deep_link", postgresql.JSONB()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])
    op.create_index("ix_notifications_type", "notifications", ["notification_type"])
    op.create_index(
        "ix_notifications_recipient_created", "notifications", ["recipient_user_id", "created_at"]
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("channel", notification_channel, nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notification_type", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(300), nullable=False, unique=True),
        sa.Column("outbox_event_id", sa.Uuid(), sa.ForeignKey("outbox_events.id", ondelete="SET NULL")),
        sa.Column(
            "push_subscription_id",
            sa.Uuid(),
            sa.ForeignKey("push_subscriptions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status", notification_delivery_status, server_default="queued", nullable=False
        ),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sanitised_failure_reason", sa.String(300)),
        sa.Column("used_template_default", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_notification_deliveries_type", "notification_deliveries", ["notification_type"])
    op.create_index(
        "ix_notification_deliveries_attempted", "notification_deliveries", ["attempted_at"]
    )
    op.create_index(
        "ix_notification_deliveries_recipient",
        "notification_deliveries",
        ["recipient_user_id", "channel"],
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("push_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("event_reminders_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("event_invitations_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("event_changes_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("household_reminders_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("daily_briefing_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("briefing_time", sa.Time(), server_default="07:30:00", nullable=False),
        sa.Column("briefing_days", briefing_days, server_default="daily", nullable=False),
        sa.Column("empty_day_briefing_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "lock_screen_preview_level",
            lock_screen_preview_level,
            server_default="title_only",
            nullable=False,
        ),
        sa.Column("quiet_hours_start", sa.Time()),
        sa.Column("quiet_hours_end", sa.Time()),
        sa.Column("quiet_hours_critical_only", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
    )
    op.create_index(
        "ix_notification_preferences_user_id", "notification_preferences", ["user_id"], unique=True
    )

    op.create_table(
        "household_routines",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("interval_weeks", sa.Integer(), server_default="1", nullable=False),
        sa.Column("week_anchor_date", sa.Date(), nullable=False),
        sa.Column(
            "reminder_timing", routine_reminder_timing, server_default="evening_before", nullable=False
        ),
        sa.Column("is_critical", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *timestamps(),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_routine_title_nonempty"),
        sa.CheckConstraint("interval_weeks >= 1", name="ck_routine_interval_weeks"),
    )
    op.create_index("ix_routine_group_id", "household_routines", ["group_id"])
    op.create_index("ix_routine_group_enabled", "household_routines", ["group_id", "enabled"])

    op.create_table(
        "household_routine_members",
        sa.Column(
            "routine_id",
            sa.Uuid(),
            sa.ForeignKey("household_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("routine_id", "user_id", name="uq_routine_member"),
    )
    op.create_index("ix_routine_member_routine_id", "household_routine_members", ["routine_id"])
    op.create_index("ix_routine_member_user_id", "household_routine_members", ["user_id"])

    op.create_table(
        "household_routine_completions",
        sa.Column(
            "routine_id",
            sa.Uuid(),
            sa.ForeignKey("household_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *timestamps(),
        sa.UniqueConstraint("routine_id", "occurrence_date", name="uq_routine_occurrence"),
    )
    op.create_index(
        "ix_routine_completion_routine_id", "household_routine_completions", ["routine_id"]
    )
    op.create_index(
        "ix_routine_completion_date", "household_routine_completions", ["occurrence_date"]
    )

    op.create_table(
        "platform_push_settings",
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("vapid_public_key", sa.Text()),
        sa.Column("encrypted_vapid_private_key", sa.Text()),
        sa.Column("subject", sa.String(320)),
        sa.Column(
            "updated_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
        *timestamps(),
    )

    op.create_table(
        "notification_templates",
        sa.Column("template_type", sa.String(60), nullable=False),
        sa.Column("channel", notification_template_channel, nullable=False),
        sa.Column("subject", sa.String(200)),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "updated_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
        *timestamps(),
        sa.UniqueConstraint("template_type", "channel", name="uq_template_type_channel"),
    )
    op.create_index(
        "ix_notification_templates_type", "notification_templates", ["template_type"]
    )

    op.create_table(
        "notification_template_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("notification_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(200)),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column(
            "replaced_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_notification_template_revisions_template_id",
        "notification_template_revisions",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_table("notification_template_revisions")
    op.drop_table("notification_templates")
    op.drop_table("platform_push_settings")
    op.drop_table("household_routine_completions")
    op.drop_table("household_routine_members")
    op.drop_table("household_routines")
    op.drop_table("notification_preferences")
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("push_subscriptions")
    op.drop_column("child_profiles", "birthday_visible")
    op.drop_column("child_profiles", "birth_year")
    op.drop_column("child_profiles", "birth_day")
    op.drop_column("child_profiles", "birth_month")
    op.drop_column("users", "birth_year")
    op.drop_column("users", "birth_day")
    op.drop_column("users", "birth_month")
    op.drop_column("users", "timezone")
    for name in (
        "notification_template_channel",
        "routine_reminder_timing",
        "briefing_days",
        "lock_screen_preview_level",
        "notification_delivery_status",
        "notification_channel",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind())
