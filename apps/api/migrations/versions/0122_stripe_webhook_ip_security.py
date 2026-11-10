"""Add environment-local Stripe webhook IP security settings.

Revision ID: 0122_stripe_webhook_ip_security
Revises: 0121_onboarding_home_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0122_stripe_webhook_ip_security"
down_revision: str | None = "0121_onboarding_home_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    mode = postgresql.ENUM("monitoring", "enforcement", name="stripe_webhook_ip_security_mode")
    op.create_table(
        "stripe_webhook_ip_security_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("mode", mode, server_default="monitoring", nullable=False),
        sa.Column("trusted_ips", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.String(length=500), nullable=True),
        sa.Column("blocked_request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_administrator_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_administrator_id"],
            ["platform_administrators.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_ip_security_settings")
    sa.Enum(name="stripe_webhook_ip_security_mode").drop(op.get_bind(), checkfirst=True)
