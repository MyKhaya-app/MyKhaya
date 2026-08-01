"""Preserve the historical migration identifier after role-model consolidation."""

from collections.abc import Sequence

revision: str = "0005_platform_role_enum_compat"
down_revision: str | None = "0004_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0002 already creates the authoritative isolated administrator role enum.
    return


def downgrade() -> None:
    return
