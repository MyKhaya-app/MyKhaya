"""Add soft-clear state for user notification history.

Clearing a notification hides it from the future consumer Notification Centre
without deleting the canonical notification or its delivery diagnostics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074_notification_clear_state"
down_revision: str | None = "0073_list_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Keep the existing (recipient_user_id, created_at) index: it remains the
    # best covering order for newest-first history. This partial index adds
    # the distinct access path for visible/unread filtering without putting
    # cleared rows into that scan or creating a redundant all-row index.
    op.create_index(
        "ix_notifications_recipient_visible_read_created",
        "notifications",
        ["recipient_user_id", "read_at", "created_at"],
        postgresql_where=sa.text("cleared_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_recipient_visible_read_created",
        table_name="notifications",
    )
    op.drop_column("notifications", "cleared_at")
