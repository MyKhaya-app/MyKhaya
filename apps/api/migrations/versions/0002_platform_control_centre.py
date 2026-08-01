"""Compatibility bridge revision for previously stamped environments."""

from collections.abc import Sequence

revision: str = "0002_platform_control_centre"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op compatibility revision."""


def downgrade() -> None:
    """No-op compatibility revision."""
