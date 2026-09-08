"""Add a third User/Home lifecycle state: Archived.

Purely additive: one nullable `archived_at` column on `users` and one on
`groups`, alongside the existing `is_active`/`suspended_at` pair rather than
replacing them (see mykhaya.routers.platform.archive_user/restore_user and
archive_home/restore_home). No existing row's meaning changes — every
current Active row stays Active (archived_at stays NULL, is_active stays
true) and every current Disabled/suspended row stays Disabled (archived_at
stays NULL, is_active stays false); nothing becomes Archived through this
migration. The three states are:

  Active:   is_active = true,  archived_at IS NULL
  Disabled: is_active = false, archived_at IS NULL
  Archived: is_active = false, archived_at IS NOT NULL

No index: `suspended_at`, the existing precedent this mirrors, has none
either, and both tables are small platform-admin-scale collections queried
by id far more often than filtered by lifecycle state.

Revision ID: 0053_lifecycle_archived_state
Revises: 0052_home_join_codes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_lifecycle_archived_state"
down_revision: str | None = "0052_home_join_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("groups", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("groups", "archived_at")
    op.drop_column("users", "archived_at")
