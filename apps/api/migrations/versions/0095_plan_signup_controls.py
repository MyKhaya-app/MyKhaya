"""Add independent Family and Ultimate acquisition controls."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0095_plan_signup_controls"
down_revision: str | None = "0094_ultimate_stripe_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_stripe_settings",
        sa.Column("family_signups_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "platform_stripe_settings",
        sa.Column("ultimate_signups_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE platform_stripe_settings SET family_signups_enabled = acquisition_enabled"
    )


def downgrade() -> None:
    op.drop_column("platform_stripe_settings", "ultimate_signups_enabled")
    op.drop_column("platform_stripe_settings", "family_signups_enabled")
