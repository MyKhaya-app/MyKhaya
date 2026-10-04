"""Add 'nudges' to the feature_key enum: Phase 2A module-governance work.

Nudges (Routines + Reminders + To-dos) has been extensively implemented for
several migrations already (0056-0060) but has never had its own FeatureKey —
its routes have gated on FeatureKey.notifications instead, which conflates
core notification-delivery infrastructure with a genuine, independently
toggleable Home module. This migration only adds the new enum value; it
seeds no data. See mykhaya.module_registry and the following migration
(0062_nudges_feature_flag_seed).

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't *used* in that same transaction (see
0054_notification_lifecycle_skip's downgrade note for the same constraint) —
this is why the FeatureFlag seed insert is a separate, later migration
rather than being combined with this one.

Revision ID: 0061_nudges_feature_key
Revises: 0060_nudge_categories
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061_nudges_feature_key"
down_revision: str | None = "0060_nudge_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Alembic's outer migration transaction must be committed before 0062 can
    # use the newly added enum value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE feature_key ADD VALUE IF NOT EXISTS 'nudges'")


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in PostgreSQL — see
    # 0054_notification_lifecycle_skip's downgrade for the same reasoning.
    # The following migration (0062) removes the row that uses this value
    # before this one's downgrade would ever run, so leaving the enum value
    # defined here is not unsafe.
    pass
