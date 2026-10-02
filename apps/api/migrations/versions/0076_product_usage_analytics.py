"""Add privacy-minimised product usage events and daily aggregates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076_product_usage_analytics"
down_revision: str | None = "0075_native_push_apns_env"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT = postgresql.ENUM(
    "app_open", "calendar_viewed", "calendar_event_created", "nudges_viewed",
    "nudge_completed", "lists_viewed", "list_created", "list_item_completed",
    "meal_plan_viewed", "meal_added", "notification_opened", "home_viewed",
    "family_viewed", name="product_usage_event_name",
)
_PLATFORM = postgresql.ENUM("web", "ios", "android", name="product_usage_platform")
_MODULE = postgresql.ENUM(
    "app", "calendar", "nudges", "lists", "meals", "notifications", "family",
    "home", "settings", name="product_usage_module",
)
_EVENT_REF = postgresql.ENUM(name="product_usage_event_name", create_type=False)
_PLATFORM_REF = postgresql.ENUM(name="product_usage_platform", create_type=False)
_MODULE_REF = postgresql.ENUM(name="product_usage_module", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _EVENT.create(bind)
    _PLATFORM.create(bind)
    _MODULE.create(bind)
    op.create_table(
        "product_usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_name", _EVENT_REF, nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="SET NULL")),
        sa.Column("platform", _PLATFORM_REF, nullable=False),
        sa.Column("module", _MODULE_REF),
        sa.Column("app_version", sa.String(80)),
        sa.Column("usage_session_id", sa.String(64)),
        sa.Column("event_key", sa.String(120)),
        sa.UniqueConstraint("event_key", name="uq_product_usage_events_event_key"),
    )
    op.create_index(
        "ix_product_usage_events_occurred", "product_usage_events", ["occurred_at"]
    )
    op.create_index(
        "ix_product_usage_events_user_occurred", "product_usage_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_product_usage_events_group_occurred", "product_usage_events",
        ["group_id", "occurred_at"],
    )
    op.create_index(
        "ix_product_usage_events_event_occurred", "product_usage_events",
        ["event_name", "occurred_at"],
    )
    op.create_table(
        "product_usage_daily_aggregates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reporting_date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("module", _MODULE_REF),
        sa.Column("platform", _PLATFORM_REF),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "reporting_date", "metric", "module", "platform",
            name="uq_product_usage_daily_dimension",
        ),
    )
    op.create_index(
        "ix_product_usage_daily_reporting_date", "product_usage_daily_aggregates",
        ["reporting_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_usage_daily_reporting_date",
        table_name="product_usage_daily_aggregates",
    )
    op.drop_table("product_usage_daily_aggregates")
    for name in (
        "ix_product_usage_events_event_occurred",
        "ix_product_usage_events_group_occurred",
        "ix_product_usage_events_user_occurred",
        "ix_product_usage_events_occurred",
    ):
        op.drop_index(name, table_name="product_usage_events")
    op.drop_table("product_usage_events")
    _MODULE.drop(op.get_bind())
    _PLATFORM.drop(op.get_bind())
    _EVENT.drop(op.get_bind())
