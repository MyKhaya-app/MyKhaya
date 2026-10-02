"""Phase 3 of MyKhaya's commercial architecture: Stripe as the first real paid
billing provider. Adds the minimum schema Stripe integration needs beyond
what Phase 1 already reserved (external_customer_id, external_subscription_id,
current_period_start/end, billing_owner_user_id) — see
docs/architecture/commercial-entitlements.md.

- home_subscriptions.external_customer_id becomes unique: one Stripe Customer
  must never be attached to more than one Home.
- home_subscriptions.external_price_id: the exact Stripe Price a subscription
  is actually billed against, independent of whatever price is currently
  configured for new signups (grandfathering).
- home_subscriptions.billing_interval: month/year, null for free/complimentary.
- stripe_webhook_events: durable, transactional webhook deduplication.

Revision ID: 0021_stripe_billing
Revises: 0020_commercial_entitlements
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_stripe_billing"
down_revision: str | None = "0020_commercial_entitlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BILLING_INTERVAL = postgresql.ENUM("month", "year", name="billing_interval", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _BILLING_INTERVAL.create(bind)

    op.add_column(
        "home_subscriptions",
        sa.Column("external_price_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_home_subscriptions_external_price_id",
        "home_subscriptions",
        ["external_price_id"],
    )
    op.add_column(
        "home_subscriptions",
        sa.Column("billing_interval", _BILLING_INTERVAL, nullable=True),
    )

    # external_customer_id already has a plain (non-unique) index from 0020;
    # replace it with a unique one — no existing row has a non-null value yet
    # (Stripe integration didn't exist before this migration), so this is safe.
    op.drop_index("ix_home_subscriptions_external_customer_id", table_name="home_subscriptions")
    op.create_index(
        "ix_home_subscriptions_external_customer_id",
        "home_subscriptions",
        ["external_customer_id"],
        unique=True,
    )

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_message", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_stripe_webhook_events_group_id", "stripe_webhook_events", ["group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_events_group_id", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")

    op.drop_index("ix_home_subscriptions_external_customer_id", table_name="home_subscriptions")
    op.create_index(
        "ix_home_subscriptions_external_customer_id",
        "home_subscriptions",
        ["external_customer_id"],
    )

    op.drop_column("home_subscriptions", "billing_interval")
    op.drop_index(
        "ix_home_subscriptions_external_price_id", table_name="home_subscriptions"
    )
    op.drop_column("home_subscriptions", "external_price_id")

    op.execute("DROP TYPE billing_interval")
