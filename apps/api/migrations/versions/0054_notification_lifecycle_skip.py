"""Add 'skipped' to notification_delivery_status: Slice 4.5 lifecycle
enforcement.

A push/email delivery suppressed because its recipient User or target Group
went inactive (Disabled or Archived) between enqueue and dispatch is a
deliberate policy decision, not a delivery failure — using the existing
`cancelled` value would conflate "this device/address is permanently
invalid" with "we chose not to send this". `skipped` is its own terminal
value (no retry either way) so PCC diagnostics can tell the two apart; see
mykhaya.worker._process_push/_process_native_push/_process_email.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't *used* in that same transaction, which holds here.

Revision ID: 0054_notification_lifecycle_skip
Revises: 0053_lifecycle_archived_state
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054_notification_lifecycle_skip"
down_revision: str | None = "0053_lifecycle_archived_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_delivery_status ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in PostgreSQL — see migration
    # 0038_household_adult's downgrade for the same reasoning. This
    # migration never assigns 'skipped' to any row itself, so leaving the
    # value defined on downgrade is not unsafe.
    pass
