"""Make Budget platform-available while retaining Home-level opt-in."""

import sqlalchemy as sa
from alembic import op

revision: str = "0082_budget_platform_rollout"
down_revision: str | None = "0081_budget_disabled_by_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The platform flag means PCC may offer the existing Home override. The
    # application resolver keeps absent Home overrides disabled for Budget.
    op.execute(
        sa.text(
            "UPDATE feature_flags SET enabled = true, release_state = 'released', updated_at = now() "
            "WHERE key = 'budget'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE feature_flags SET enabled = false WHERE key = 'budget'"))
