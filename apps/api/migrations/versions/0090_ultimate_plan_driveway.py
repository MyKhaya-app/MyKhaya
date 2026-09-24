"""Add the `ultimate` subscription plan and `driveway` feature key.

Both are additive enum values only. `ultimate` becomes usable by
mykhaya.entitlements once PLAN_DEFINITIONS carries an entry for it (see the
application-layer change alongside this migration); no HomeSubscription row
is altered here. `driveway` remains globally off until a later migration
seeds its disabled-by-default FeatureFlag row, mirroring the Budget/Support
precedent (0079/0081, 0087/0088).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0090_ultimate_plan_driveway"
down_revision: str | None = "0089_budget_fixed_actual"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL does not allow a newly-added enum value to be used until the
    # transaction that adds it has committed, so both ADD VALUEs must commit
    # before any later migration can reference them (e.g. inserting a
    # feature_flags row keyed 'driveway', or writing a HomeSubscription with
    # plan='ultimate').
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE subscription_plan ADD VALUE IF NOT EXISTS 'ultimate'")
        op.execute("ALTER TYPE feature_key ADD VALUE IF NOT EXISTS 'driveway'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely. Both values remain
    # harmless if unused, and the next migration can continue from this state.
    pass
