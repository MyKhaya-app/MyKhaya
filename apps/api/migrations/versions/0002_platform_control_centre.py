"""Add the isolated platform control-centre and public-status foundation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "0002_platform_control_centre"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    platform_role = postgresql.ENUM(
        "platform_owner", "platform_administrator", "support_operator",
        "security_operator", "read_only_operator", name="platform_role", create_type=False
    )
    feature_key = postgresql.ENUM(
        "calendar", "tasks", "shopping", "meals", "plans", "wish_lists",
        "notifications", "external_sharing", name="feature_key", create_type=False
    )
    service_state = postgresql.ENUM(
        "operational", "degraded_performance", "partial_outage", "major_outage",
        "maintenance", name="service_state", create_type=False
    )
    platform_role.create(op.get_bind())
    feature_key.create(op.get_bind())
    service_state.create(op.get_bind())

    for table in ("users", "groups"):
        op.add_column(table, sa.Column("last_activity_at", sa.DateTime(timezone=True)))
        op.add_column(table, sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.add_column("groups", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False))

    op.create_table(
        "platform_administrators",
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", platform_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("mfa_enrolled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index("ix_platform_administrators_email", "platform_administrators", ["email"], unique=True)
    op.create_table(
        "platform_sessions",
        sa.Column("administrator_id", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(300), nullable=False),
        sa.Column("source_ip", sa.String(64), nullable=False),
        *timestamps(),
    )
    for name, columns, unique in (
        ("ix_platform_sessions_administrator_id", ["administrator_id"], False),
        ("ix_platform_sessions_token_hash", ["token_hash"], True),
        ("ix_platform_sessions_idle_expires_at", ["idle_expires_at"], False),
        ("ix_platform_sessions_absolute_expires_at", ["absolute_expires_at"], False),
    ):
        op.create_index(name, "platform_sessions", columns, unique=unique)
    op.create_table(
        "administrative_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("administrator_id", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        sa.Column("administrator_role", sa.String(40), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(80)), sa.Column("target_id", sa.Uuid()),
        sa.Column("outcome", sa.String(30), nullable=False), sa.Column("reason", sa.String(500)),
        sa.Column("source_ip", sa.String(64), nullable=False), sa.Column("request_id", sa.String(80)),
        sa.Column("session_reference", sa.String(64)),
        sa.Column("previous_values", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("new_values", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("failure_category", sa.String(80)),
    )
    op.create_index("ix_admin_audit_created", "administrative_audit_events", ["created_at"])
    op.create_index("ix_admin_audit_target", "administrative_audit_events", ["target_type", "target_id"])
    op.create_table(
        "administrative_notes",
        sa.Column("administrator_id", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False), sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False), *timestamps(),
    )
    op.create_index("ix_admin_note_target", "administrative_notes", ["target_type", "target_id"])
    op.create_table(
        "security_events", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("administrator_id", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        sa.Column("source_ip", sa.String(64)), sa.Column("request_id", sa.String(80)),
        sa.Column("safe_detail", sa.String(500)),
    )
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_severity", "security_events", ["severity"])
    op.create_table(
        "platform_settings", sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        *timestamps(),
    )
    op.create_index("ix_platform_settings_key", "platform_settings", ["key"], unique=True)
    op.create_table(
        "feature_flags", sa.Column("key", feature_key, nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        *timestamps(),
    )
    op.create_table(
        "feature_overrides", sa.Column("feature_key", feature_key, nullable=False),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        *timestamps(), sa.UniqueConstraint("feature_key", "group_id", name="uq_feature_group"),
    )
    op.create_table(
        "public_incidents", sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False), sa.Column("service", sa.String(40), nullable=False),
        sa.Column("state", service_state, nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="RESTRICT"), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "operational_heartbeats", sa.Column("service", sa.String(40), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("safe_detail", sa.String(300)),
    )


def downgrade() -> None:
    for table in (
        "operational_heartbeats", "public_incidents", "feature_overrides", "feature_flags",
        "platform_settings", "security_events", "administrative_notes",
        "administrative_audit_events", "platform_sessions", "platform_administrators",
    ):
        op.drop_table(table)
    op.drop_column("groups", "is_active")
    for table in ("groups", "users"):
        op.drop_column(table, "suspended_at")
        op.drop_column(table, "last_activity_at")
    op.drop_column("users", "last_login_at")
    postgresql.ENUM(name="service_state").drop(op.get_bind())
    postgresql.ENUM(name="feature_key").drop(op.get_bind())
    postgresql.ENUM(name="platform_role").drop(op.get_bind())
