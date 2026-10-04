"""Add per-plan Ultimate Stripe Price IDs.

Stripe credentials remain shared per mode; only the configured acquisition
prices are plan-specific. Existing Family values are preserved unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0094_ultimate_stripe_prices"
down_revision: str | None = "0093_driveway_reminder_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_stripe_settings",
        sa.Column("test_ultimate_monthly_price_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "platform_stripe_settings",
        sa.Column("test_ultimate_annual_price_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "platform_stripe_settings",
        sa.Column("live_ultimate_monthly_price_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "platform_stripe_settings",
        sa.Column("live_ultimate_annual_price_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_stripe_settings", "live_ultimate_annual_price_id")
    op.drop_column("platform_stripe_settings", "live_ultimate_monthly_price_id")
    op.drop_column("platform_stripe_settings", "test_ultimate_annual_price_id")
    op.drop_column("platform_stripe_settings", "test_ultimate_monthly_price_id")
