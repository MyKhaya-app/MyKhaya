"""Add Platform-Admin-managed Stripe configuration.

Single-row table for Stripe billing credentials, editable through the Platform
Control Centre Payments page. Unlike platform_smtp_settings/platform_push_settings,
this row — once `enabled` — takes precedence *over* the MYKHAYA_STRIPE_* environment
variables rather than the other way round (see
mykhaya.billing.config.resolve_stripe_config and
docs/architecture/platform-control-centre.md#stripe-configuration-precedence).

Test and Live credentials are stored in separate columns so switching `mode` can never
mix them. The secret key and webhook signing secret are stored encrypted per mode
(mykhaya.secrets_crypto.encrypt_stripe_secret) — this migration only creates the
ciphertext columns, it never writes a plaintext value.

Revision ID: 0027_platform_stripe_settings
Revises: 0026_daily_routine_recurrence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_platform_stripe_settings"
down_revision: str | None = "0026_daily_routine_recurrence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    stripe_mode = postgresql.ENUM("test", "live", name="stripe_mode", create_type=False)
    stripe_mode.create(op.get_bind())

    op.create_table(
        "platform_stripe_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mode", stripe_mode, server_default="test", nullable=False),
        sa.Column("test_publishable_key", sa.String(200)),
        sa.Column("encrypted_test_secret_key", sa.Text()),
        sa.Column("encrypted_test_webhook_secret", sa.Text()),
        sa.Column("test_family_monthly_price_id", sa.String(200)),
        sa.Column("test_family_annual_price_id", sa.String(200)),
        sa.Column("live_publishable_key", sa.String(200)),
        sa.Column("encrypted_live_secret_key", sa.Text()),
        sa.Column("encrypted_live_webhook_secret", sa.Text()),
        sa.Column("live_family_monthly_price_id", sa.String(200)),
        sa.Column("live_family_annual_price_id", sa.String(200)),
        sa.Column(
            "updated_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_stripe_settings")
    postgresql.ENUM(name="stripe_mode").drop(op.get_bind())
