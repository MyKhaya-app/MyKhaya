"""Add persistent, independently revocable family-app trusted devices.

Trusted devices are deliberately separate from Platform Control Centre sessions.
Only the family web cookie flow uses this table; the raw rotating credential is
never persisted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_trusted_devices"
down_revision: str | None = "0028_personal_calendars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

session_kind = postgresql.ENUM("adult", "managed_child", name="session_kind", create_type=False)


def upgrade() -> None:
    op.create_table(
        "trusted_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", session_kind, nullable=False, server_default="adult"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("device_name", sa.String(120), nullable=False, server_default="MyKhaya device"),
        sa.Column("platform", sa.String(80), nullable=False, server_default="Unknown platform"),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default="Unknown device"),
        sa.Column("ip_created", sa.String(80)),
        sa.Column("ip_last_seen", sa.String(80)),
    )
    op.create_index("ix_trusted_devices_user_id", "trusted_devices", ["user_id"])
    op.create_index(
        "ix_trusted_devices_user_active",
        "trusted_devices",
        ["user_id", "revoked_at", "expires_at"],
    )
    op.create_index("ix_trusted_devices_expires_at", "trusted_devices", ["expires_at"])
    op.add_column(
        "sessions",
        sa.Column("trusted_device_id", sa.Uuid(), sa.ForeignKey("trusted_devices.id", ondelete="SET NULL")),
    )
    op.create_index("ix_sessions_trusted_device_id", "sessions", ["trusted_device_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_trusted_device_id", table_name="sessions")
    op.drop_column("sessions", "trusted_device_id")
    op.drop_index("ix_trusted_devices_expires_at", table_name="trusted_devices")
    op.drop_index("ix_trusted_devices_user_active", table_name="trusted_devices")
    op.drop_index("ix_trusted_devices_user_id", table_name="trusted_devices")
    op.drop_table("trusted_devices")
