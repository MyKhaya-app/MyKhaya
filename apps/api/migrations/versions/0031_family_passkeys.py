"""Add adult family-user passkeys and fresh-auth session tracking."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_family_passkeys"
down_revision: str | None = "0030_home_calendar_colour"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("fresh_auth_at", sa.DateTime(timezone=True)))
    op.create_table(
        "user_passkeys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.String(255), nullable=False, unique=True),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(100), nullable=False, server_default="Passkey 1"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_user_passkeys_user_id", "user_passkeys", ["user_id"])
    op.create_index("ix_user_passkeys_credential_id", "user_passkeys", ["credential_id"])
    op.create_index("ix_user_passkeys_user_active", "user_passkeys", ["user_id", "revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_user_passkeys_user_active", table_name="user_passkeys")
    op.drop_index("ix_user_passkeys_credential_id", table_name="user_passkeys")
    op.drop_index("ix_user_passkeys_user_id", table_name="user_passkeys")
    op.drop_table("user_passkeys")
    op.drop_column("sessions", "fresh_auth_at")
