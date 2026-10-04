"""Persist safe Stripe billing stage diagnostics for PCC.

Revision ID: 0034_stripe_billing_diagnostics
Revises: 0033_stripe_acquisition_control
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0034_stripe_billing_diagnostics"
down_revision: str | None = "0033_stripe_acquisition_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_billing_diagnostics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("stripe_mode", sa.String(length=10), nullable=True),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("stripe_subscription_status", sa.String(length=40), nullable=True),
        sa.Column("stored_subscription_status", sa.String(length=40), nullable=True),
        sa.Column("stored_plan", sa.String(length=40), nullable=True),
        sa.Column("effective_plan", sa.String(length=40), nullable=True),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("safe_error_message", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stripe_billing_diagnostics_created_at", "stripe_billing_diagnostics", ["created_at"])
    op.create_index("ix_stripe_billing_diagnostics_source", "stripe_billing_diagnostics", ["source"])
    op.create_index("ix_stripe_billing_diagnostics_result", "stripe_billing_diagnostics", ["result"])
    op.create_index("ix_stripe_billing_diagnostics_stripe_event_id", "stripe_billing_diagnostics", ["stripe_event_id"])
    op.create_index("ix_stripe_billing_diagnostics_checkout_session_id", "stripe_billing_diagnostics", ["checkout_session_id"])
    op.create_index("ix_stripe_billing_diagnostics_group_id", "stripe_billing_diagnostics", ["group_id"])


def downgrade() -> None:
    op.drop_table("stripe_billing_diagnostics")
