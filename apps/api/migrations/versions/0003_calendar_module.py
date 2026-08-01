"""Compatibility bridge revision for existing 0003-stamped databases."""

from collections.abc import Sequence

revision: str = "0003_calendar_module"
down_revision: str | None = "0002_platform_control_centre"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op compatibility revision."""


def downgrade() -> None:
    """No-op compatibility revision."""
