"""Seed the central feature-flag catalogue with disabled defaults."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_feature_flags"
down_revision: str | None = "0003_calendar_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEATURE_KEYS = (
    "calendar",
    "tasks",
    "shopping",
    "meals",
    "plans",
    "wish_lists",
    "notifications",
    "external_sharing",
)


def upgrade() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO feature_flags (id, key, enabled)
        SELECT :id, CAST(:key AS feature_key), false
        WHERE NOT EXISTS (
            SELECT 1 FROM feature_flags WHERE key = CAST(:key AS feature_key)
        )
        """
    )
    for key in FEATURE_KEYS:
        bind.execute(statement, {"id": uuid.uuid4(), "key": key})


def downgrade() -> None:
    bind = op.get_bind()
    delete_overrides = sa.text(
        "DELETE FROM feature_overrides WHERE feature_key = CAST(:key AS feature_key)"
    )
    delete_flags = sa.text(
        "DELETE FROM feature_flags WHERE key = CAST(:key AS feature_key)"
    )
    for key in FEATURE_KEYS:
        bind.execute(delete_overrides, {"key": key})
        bind.execute(delete_flags, {"key": key})
