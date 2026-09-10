"""Critical pre-condition for the Phase 2A PCC-platform-precedence fix:
seed the global FeatureFlag enabled=true for every currently *released*
(non-beta, non-hidden) module whose global flag was never promoted.

mykhaya.features.is_feature_enabled previously let a Home's FeatureOverride
bypass a disabled/missing global FeatureFlag. Correcting that precedence
(PCC platform availability now authoritative — see mykhaya/features.py and
docs/architecture/feature-flags.md) means, for the first time, the global
flag actually matters for every module, not just the ones a PCC operator
happened to promote (until now, only 'notifications' was ever promoted, by
0046_notifications_module_released, for exactly this same reason).

Inspecting this deployment's own data before writing this migration found
'calendar' and 'wish_lists' still globally disabled (enabled=false) despite
being in active per-Home use purely via FeatureOverride rows — i.e. every
Home currently using Calendar or Wishlists is, today, relying on the exact
bypass bug this phase fixes. Deploying the precedence correction alone,
without this backfill, would immediately break Calendar and Wishlists for
every such Home. 'shopping' (Lists) and 'meals' were already enabled=true
globally in this deployment's data, so this migration is a no-op for them
(ON CONFLICT DO UPDATE, idempotent either way) — included for completeness
and so this migration's intent doesn't silently depend on a snapshot of one
environment's current data.

'external_sharing' is deliberately NOT included: it is release_state=beta
(a genuinely limited/opt-in rollout, unlike the four modules above), and
this deployment's data showed no Home currently holds a FeatureOverride for
it — there is no evidence of live reliance to preserve, and blanket-
enabling a beta module globally is a platform rollout decision for a PCC
operator to make deliberately, not something to backfill on their behalf.
'tasks' and 'plans' remain hidden and are unaffected either way (hidden
modules fail closed regardless of flag/override state).

Revision ID: 0063_feature_flag_backfill
Revises: 0062_nudges_feature_flag_seed
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063_feature_flag_backfill"
down_revision: str | None = "0062_nudges_feature_flag_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = ("calendar", "shopping", "meals", "wish_lists")


def upgrade() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
        VALUES (:id, now(), now(), CAST(:key AS feature_key), true, 'released')
        ON CONFLICT (key) DO UPDATE
        SET enabled = true, release_state = 'released', updated_at = now()
        """
    )
    for key in _KEYS:
        bind.execute(statement, {"id": uuid.uuid4(), "key": key})


def downgrade() -> None:
    # Deliberately a no-op: this migration only ever moved these flags
    # towards the state module_registry.py already declares for them
    # (released, in active per-Home use) — reverting it would recreate the
    # exact "Home override alone controls access" gap this phase fixed, for
    # every Home that has these four modules enabled today.
    pass
