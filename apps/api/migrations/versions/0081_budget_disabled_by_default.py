"""Make the Budget platform rollout explicitly disabled by default."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081_budget_disabled_by_default"
down_revision: str | None = "0080_budget_month_start"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A previous local/bootstrap state may already contain the newly-added
    # enum value with an incorrect platform row. Normalize it without
    # touching any Home override or personal Budget data.
    op.execute(
        sa.text(
            """
            INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
            VALUES (:id, now(), now(), 'budget', false, 'released')
            ON CONFLICT (key) DO UPDATE
            SET enabled = false, release_state = 'released', updated_at = now()
            """
        ).bindparams(id=uuid.uuid4())
    )


def downgrade() -> None:
    # Keep the feature flag explicitly off when rolling back this rollout
    # control migration; removing it would make the platform state ambiguous.
    op.execute(sa.text("UPDATE feature_flags SET enabled = false WHERE key = 'budget'"))
