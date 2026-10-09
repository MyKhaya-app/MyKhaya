"""Add bearer-authenticated native push registrations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_native_push_devices"
down_revision: str | None = "0019_platform_admin_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "native_push_devices",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("installation_id", sa.String(128), nullable=False),
        sa.Column("device_label", sa.String(120)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_reason", sa.String(200)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform", "installation_id", name="uq_native_push_device_installation"),
    )
    op.create_index("ix_native_push_devices_user_id", "native_push_devices", ["user_id"])
    op.create_index("ix_native_push_devices_user", "native_push_devices", ["user_id", "disabled_at"])


def downgrade() -> None:
    op.drop_index("ix_native_push_devices_user", table_name="native_push_devices")
    op.drop_index("ix_native_push_devices_user_id", table_name="native_push_devices")
    op.drop_table("native_push_devices")
