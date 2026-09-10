"""Add 'free_demo' to the managed_demo_type enum: Free Plan Demo fixture.

A new Managed Demo/Test Home template that resolves to the real Free plan
(SubscriptionPlan.free) through the normal entitlement path, distinct from
`apple_review`/`demo`, which both resolve to a complimentary Family
subscription. See mykhaya.managed_demo_homes.seed_template.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't *used* in that same transaction — see
0061_nudges_feature_key for the same constraint. Nothing else in this
migration references 'free_demo', so a single migration is sufficient here.

Revision ID: 0064_free_demo_managed_type
Revises: 0063_feature_flag_backfill
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064_free_demo_managed_type"
down_revision: str | None = "0063_feature_flag_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE managed_demo_type ADD VALUE IF NOT EXISTS 'free_demo'")


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in PostgreSQL — see 0061's downgrade for
    # the same reasoning. No row created by this migration references the
    # value, so leaving it defined here is not unsafe.
    pass
