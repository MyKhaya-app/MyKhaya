"""Add the PCC Stripe new-subscription acquisition switch.

Revision ID: 0033_stripe_acquisition_control
Revises: 0032_passkey_attachment
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0033_stripe_acquisition_control"
down_revision: str | None = "0032_passkey_attachment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_stripe_settings",
        sa.Column("acquisition_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("platform_stripe_settings", "acquisition_enabled")
