"""Seed the Support platform rollout row, explicitly disabled by default —
same pattern as 0081_budget_disabled_by_default. Kept as its own migration,
after 0087's enum-value addition, so the 'support' feature_key value is
guaranteed committed and visible before this INSERT uses it."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088_support_disabled_by_default"
down_revision: str | None = "0087_support_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
            VALUES (:id, now(), now(), 'support', false, 'beta')
            ON CONFLICT (key) DO UPDATE
            SET enabled = false, release_state = 'beta', updated_at = now()
            """
        ).bindparams(id=uuid.uuid4())
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM feature_flags WHERE key = 'support'"))
