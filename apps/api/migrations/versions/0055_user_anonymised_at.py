"""Add User.anonymised_at: Slice 5B (PCC User anonymisation).

Distinct from `archived_at`. Archived is reversible (Restore clears it);
anonymised is destructive and permanent — once set, Restore must refuse
(see routers.platform.restore_user) rather than resurrect an account whose
PII has already been overwritten. Purely additive: one nullable column,
every existing User gets NULL (never anonymised).

Revision ID: 0055_user_anonymised_at
Revises: 0054_notification_lifecycle_skip
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_user_anonymised_at"
down_revision: str | None = "0054_notification_lifecycle_skip"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "anonymised_at")
