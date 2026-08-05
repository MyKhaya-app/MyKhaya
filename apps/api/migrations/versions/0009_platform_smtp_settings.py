"""Add Platform-Admin-managed SMTP configuration.

Single-row table for outbound email transport settings, used only when no
MYKHAYA_SMTP_* environment override is active. The password is stored encrypted
(mykhaya.secrets_crypto) — this migration only creates the ciphertext column, it never
writes a plaintext value.

Revision ID: 0009_platform_smtp_settings
Revises: 0008_member_colour
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_platform_smtp_settings"
down_revision: str | None = "0008_member_colour"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    smtp_connection_security = postgresql.ENUM(
        "none", "starttls", "tls", name="smtp_connection_security", create_type=False
    )
    smtp_connection_security.create(op.get_bind())

    op.create_table(
        "platform_smtp_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("host", sa.String(255), server_default="", nullable=False),
        sa.Column("port", sa.Integer(), server_default="587", nullable=False),
        sa.Column(
            "connection_security",
            smtp_connection_security,
            server_default="starttls",
            nullable=False,
        ),
        sa.Column("auth_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("username", sa.String(320)),
        sa.Column("encrypted_password", sa.Text()),
        sa.Column("sender_name", sa.String(100), server_default="MyKhaya", nullable=False),
        sa.Column("sender_email", sa.String(320), server_default="", nullable=False),
        sa.Column("reply_to", sa.String(320)),
        sa.Column("timeout_seconds", sa.Integer(), server_default="10", nullable=False),
        sa.Column(
            "updated_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_smtp_settings")
    postgresql.ENUM(name="smtp_connection_security").drop(op.get_bind())
