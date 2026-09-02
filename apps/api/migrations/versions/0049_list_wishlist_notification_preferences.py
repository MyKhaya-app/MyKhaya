"""Add Lists and Wishlist notification preference categories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_list_wishlist_notification_preferences"
down_revision: str | None = "0048_native_push_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column("list_assignments_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("wishlist_sharing_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "wishlist_sharing_enabled")
    op.drop_column("notification_preferences", "list_assignments_enabled")
