"""Ensure platform_role enum includes current role labels."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_platform_role_enum_compat"
down_revision: str | None = "0004_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PLATFORM_ROLE_VALUES = (
    "owner",
    "administrator",
    "support_operator",
    "read_only_operator",
)


def upgrade() -> None:
    for value in PLATFORM_ROLE_VALUES:
        op.execute(sa.text(f"ALTER TYPE platform_role ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    # Enum label removal is intentionally unsupported because PostgreSQL cannot
    # safely drop individual enum values in-place.
    return
