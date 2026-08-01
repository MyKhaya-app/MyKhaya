"""Add home calendar, events, labels, members, and activity tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_calendar_module"
down_revision: str | None = "0002_platform_control_centre"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    recurrence = postgresql.ENUM(
        "none",
        "daily",
        "weekly",
        "monthly",
        "yearly",
        "weekdays",
        name="recurrence_pattern",
        create_type=False,
    )
    recurrence.create(op.get_bind())

    op.create_table(
        "home_calendars",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "is_primary", name="uq_home_primary_calendar"),
    )
    op.create_index("ix_home_calendars_group_id", "home_calendars", ["group_id"])

    op.create_table(
        "calendar_event_labels",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "name", name="uq_event_label_group_name"),
    )
    op.create_index("ix_calendar_event_labels_group_id", "calendar_event_labels", ["group_id"])
    op.create_index("ix_event_label_group_sort", "calendar_event_labels", ["group_id", "sort_order"])

    op.create_table(
        "calendar_events",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), sa.ForeignKey("home_calendars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label_id", sa.Uuid(), sa.ForeignKey("calendar_event_labels.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.String(2000)),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_all_day", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("location_text", sa.String(200)),
        sa.Column("reminder_minutes", sa.Integer()),
        sa.Column("recurrence", recurrence, server_default="none", nullable=False),
        sa.Column("recurrence_interval", sa.Integer(), server_default="1", nullable=False),
        sa.Column("recurrence_until", sa.DateTime(timezone=True)),
        sa.Column("recurrence_count", sa.Integer()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("last_edited_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_calendar_event_title_nonempty"),
        sa.CheckConstraint("end_at >= start_at", name="ck_calendar_event_valid_range"),
        sa.CheckConstraint("recurrence_interval >= 1", name="ck_calendar_event_recur_interval"),
    )
    op.create_index("ix_calendar_events_group_id", "calendar_events", ["group_id"])
    op.create_index("ix_calendar_events_calendar_id", "calendar_events", ["calendar_id"])
    op.create_index("ix_calendar_events_label_id", "calendar_events", ["label_id"])
    op.create_index("ix_calendar_events_start_at", "calendar_events", ["start_at"])
    op.create_index("ix_calendar_events_end_at", "calendar_events", ["end_at"])
    op.create_index("ix_calendar_event_group_start", "calendar_events", ["group_id", "start_at"])
    op.create_index("ix_calendar_event_group_end", "calendar_events", ["group_id", "end_at"])
    op.create_index("ix_calendar_event_group_active", "calendar_events", ["group_id", "deleted_at"])

    op.create_table(
        "calendar_event_members",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_member"),
    )
    op.create_index("ix_calendar_event_members_group_id", "calendar_event_members", ["group_id"])
    op.create_index("ix_calendar_event_members_event_id", "calendar_event_members", ["event_id"])
    op.create_index("ix_event_member_group_user", "calendar_event_members", ["group_id", "user_id"])

    op.create_table(
        "calendar_event_activity",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_calendar_event_activity_group_id", "calendar_event_activity", ["group_id"])
    op.create_index("ix_calendar_event_activity_event_id", "calendar_event_activity", ["event_id"])
    op.create_index("ix_event_activity_event_created", "calendar_event_activity", ["event_id", "created_at"])


def downgrade() -> None:
    for table in (
        "calendar_event_activity",
        "calendar_event_members",
        "calendar_events",
        "calendar_event_labels",
        "home_calendars",
    ):
        op.drop_table(table)
    postgresql.ENUM(name="recurrence_pattern").drop(op.get_bind())
