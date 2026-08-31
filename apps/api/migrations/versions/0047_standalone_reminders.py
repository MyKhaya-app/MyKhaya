"""Add standalone Reminders: `reminders`, `reminder_members`, `reminder_completions`.

A lightweight, separate concept from HouseholdRoutine (a recurring responsibility
with its own reminder_timing) and from CalendarEvent.reminder_minutes (attached to
one event) — see mykhaya.models.Reminder's docstring and
docs/architecture/notification-engine.md. Mirrors HouseholdRoutine's
scope/owner_user_id/*Member/*Completion shape closely, including reusing the
existing `routine_scope` enum type verbatim (create_type=False below) rather than
creating a duplicate `reminder_scope` type with identical values — the two enums
are conceptually the same "personal vs household" split.

Purely additive: three new tables, two new enum types, no existing table touched.

Revision ID: 0047_standalone_reminders
Revises: 0046_notifications_released
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047_standalone_reminders"
down_revision: str | None = "0046_notifications_released"
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
    bind = op.get_bind()
    reminder_repeat = postgresql.ENUM(
        "never", "daily", "weekly", name="reminder_repeat", create_type=False
    )
    reminder_cadence = postgresql.ENUM(
        "once", "hourly", "daily", "weekly", name="reminder_cadence", create_type=False
    )
    reminder_repeat.create(bind)
    reminder_cadence.create(bind)
    routine_scope = postgresql.ENUM(
        "personal", "household", name="routine_scope", create_type=False
    )

    op.create_table(
        "reminders",
        sa.Column(
            "group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("scope", routine_scope, server_default="household", nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("due_time", sa.Time(), nullable=False),
        sa.Column("repeat", reminder_repeat, server_default="never", nullable=False),
        sa.Column("cadence", reminder_cadence, server_default="once", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_reminder_title_nonempty"),
        sa.CheckConstraint(
            "(scope = 'personal' AND owner_user_id IS NOT NULL) OR "
            "(scope = 'household' AND owner_user_id IS NULL)",
            name="ck_reminder_scope_owner",
        ),
    )
    op.create_index("ix_reminders_group_id", "reminders", ["group_id"])
    op.create_index("ix_reminders_owner_user_id", "reminders", ["owner_user_id"])
    op.create_index("ix_reminder_group_enabled", "reminders", ["group_id", "enabled"])

    op.create_table(
        "reminder_members",
        sa.Column(
            "reminder_id",
            sa.Uuid(),
            sa.ForeignKey("reminders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        *timestamps(),
        sa.UniqueConstraint("reminder_id", "user_id", name="uq_reminder_member"),
    )
    op.create_index("ix_reminder_member_reminder_id", "reminder_members", ["reminder_id"])
    op.create_index("ix_reminder_member_user_id", "reminder_members", ["user_id"])

    op.create_table(
        "reminder_completions",
        sa.Column(
            "reminder_id",
            sa.Uuid(),
            sa.ForeignKey("reminders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *timestamps(),
        sa.UniqueConstraint("reminder_id", "occurrence_date", name="uq_reminder_occurrence"),
    )
    op.create_index(
        "ix_reminder_completion_reminder_id", "reminder_completions", ["reminder_id"]
    )
    op.create_index("ix_reminder_completion_date", "reminder_completions", ["occurrence_date"])


def downgrade() -> None:
    op.drop_table("reminder_completions")
    op.drop_table("reminder_members")
    op.drop_table("reminders")
    postgresql.ENUM(name="reminder_cadence").drop(op.get_bind())
    postgresql.ENUM(name="reminder_repeat").drop(op.get_bind())
