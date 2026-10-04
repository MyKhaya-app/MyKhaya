"""Seed the global FeatureFlag row for the new 'nudges' FeatureKey: enabled.

Preserves existing behaviour for every current Home. Today, Routines/
Reminders/To-dos gate on FeatureKey.notifications, whose global FeatureFlag
was seeded enabled=true by 0046_notifications_module_released, and
is_feature_enabled() only ever reads FeatureFlag/FeatureOverride rows (a
module's ModuleDefinition.default_enabled is never itself consulted at
runtime) — so Nudges functionality is, in practice, already available on
every Home that has not explicitly overridden 'notifications' off. Once
mykhaya.routers.household_routines/reminders/todos are rewired to gate on
FeatureKey.nudges instead (application code, not this migration), seeding
this new key's global flag enabled=true reproduces that same default-on
behaviour under its own, independent identity — no existing Home gains or
loses Nudges access as a result of this migration. No per-Home
FeatureOverride rows are created here: the key did not exist before this
change, so no Home can already hold an override for it, and a global default
is sufficient to preserve current behaviour for every existing Home.

Revision ID: 0062_nudges_feature_flag_seed
Revises: 0061_nudges_feature_key
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062_nudges_feature_flag_seed"
down_revision: str | None = "0061_nudges_feature_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
        VALUES (gen_random_uuid(), now(), now(), 'nudges', true, 'released')
        ON CONFLICT (key) DO UPDATE
        SET enabled = true, release_state = 'released', updated_at = now()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM feature_overrides WHERE feature_key = 'nudges'
        """
    )
    op.execute(
        """
        DELETE FROM feature_flags WHERE key = 'nudges'
        """
    )
