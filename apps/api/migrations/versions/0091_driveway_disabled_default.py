"""Seed the Driveway platform feature flag, disabled by default."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091_driveway_disabled_default"
down_revision: str | None = "0090_ultimate_plan_driveway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
            VALUES (:id, now(), now(), 'driveway', false, 'released')
            ON CONFLICT (key) DO UPDATE
            SET enabled = false, release_state = 'released', updated_at = now()
            """
        ).bindparams(id=uuid.uuid4())
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE feature_flags SET enabled = false WHERE key = 'driveway'"))
