"""Phase 7 of MyKhaya's commercial architecture: production billing
readiness. Adds stripe_webhook_failures — an append-only observability log
for a webhook processing *failure*, deliberately separate from
stripe_webhook_events so a failed attempt keeps being retried by Stripe
rather than being permanently deduplicated away. See
docs/architecture/commercial-entitlements.md#webhook-observability.

No change to stripe_webhook_events' schema — its unused error_message
column is retained as-is (see the model docstring for why).

Revision ID: 0023_billing_readiness
Revises: 0022_multi_calendar_entitlement
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_billing_readiness"
down_revision: str | None = "0022_multi_calendar_entitlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_failures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_stripe_webhook_failures_stripe_event_id",
        "stripe_webhook_failures",
        ["stripe_event_id"],
    )
    op.create_index(
        "ix_stripe_webhook_failures_occurred_at", "stripe_webhook_failures", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_failures_occurred_at", table_name="stripe_webhook_failures")
    op.drop_index(
        "ix_stripe_webhook_failures_stripe_event_id", table_name="stripe_webhook_failures"
    )
    op.drop_table("stripe_webhook_failures")
