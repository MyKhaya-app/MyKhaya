"""Track the APNs environment for each native device registration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075_native_push_apns_env"
down_revision: str | None = "0074_notification_clear_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "native_push_devices",
        sa.Column("apns_environment", sa.String(10), nullable=True),
    )
    op.create_check_constraint(
        "ck_native_push_devices_apns_environment",
        "native_push_devices",
        "apns_environment IN ('sandbox', 'production') OR apns_environment IS NULL",
    )
    op.drop_constraint(
        "uq_native_push_device_installation",
        "native_push_devices",
        type_="unique",
    )
    # Legacy rows remain unique by installation. Known registrations are
    # independently unique per APNs environment, allowing a shared backend to
    # retain a sandbox and production registration for the same installation.
    op.create_index(
        "uq_native_push_device_legacy_installation",
        "native_push_devices",
        ["platform", "installation_id"],
        unique=True,
        postgresql_where=sa.text("apns_environment IS NULL"),
    )
    op.create_index(
        "uq_native_push_device_environment",
        "native_push_devices",
        ["platform", "installation_id", "apns_environment"],
        unique=True,
        postgresql_where=sa.text("apns_environment IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_native_push_device_environment", table_name="native_push_devices")
    op.drop_index("uq_native_push_device_legacy_installation", table_name="native_push_devices")
    op.create_unique_constraint(
        "uq_native_push_device_installation",
        "native_push_devices",
        ["platform", "installation_id"],
    )
    op.drop_constraint(
        "ck_native_push_devices_apns_environment",
        "native_push_devices",
        type_="check",
    )
    op.drop_column("native_push_devices", "apns_environment")
