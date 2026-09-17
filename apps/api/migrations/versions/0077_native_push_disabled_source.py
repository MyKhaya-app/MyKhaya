"""Track who/what disabled a native push registration (provider / user /
platform_admin) — see mykhaya.models.NativePushDisabledSource for why this
is distinct from the existing free-text disabled_reason: it lets
register_native_device()'s upsert refuse to silently reactivate a
Platform-Admin-disabled registration on the app's own next natural
re-registration, while a provider rejection or consumer logout still
reactivates exactly as before.

Nullable, no backfill — existing disabled rows (all of them predating this
column) simply have no recorded source, and are treated the same as
provider/user (eligible to reactivate) rather than platform_admin. Fully
backward compatible.

Revision ID: 0077_native_push_disabled_source
Revises: 0076_product_usage_analytics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077_native_push_disabled_source"
down_revision: str | None = "0076_product_usage_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sa.Enum("provider", "user", "platform_admin", name="native_push_disabled_source").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column(
        "native_push_devices",
        sa.Column(
            "disabled_source",
            sa.Enum(
                "provider", "user", "platform_admin",
                name="native_push_disabled_source", create_type=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("native_push_devices", "disabled_source")
    op.execute("DROP TYPE native_push_disabled_source")
