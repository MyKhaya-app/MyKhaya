"""Compatibility bridge revision for existing 0002-stamped databases."""

from collections.abc import Sequence

revision: str = "0002_platform_control_centre"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op bridge to preserve existing revision chain."""


def downgrade() -> None:
    """No-op bridge to preserve existing revision chain."""
