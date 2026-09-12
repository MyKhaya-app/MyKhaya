"""Add cached platform holiday sources and Home Calendar Highlights settings."""

from alembic import op
import sqlalchemy as sa

revision = "0071_calendar_highlights"
down_revision = "0070_consumer_mfa_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_holiday_sources",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("country_name", sa.String(100), nullable=False),
        sa.Column("flag_emoji", sa.String(8), nullable=False),
        sa.Column("region_code", sa.String(40)),
        sa.Column("region_name", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("source_url", sa.String(500)),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sync_status", sa.String(20), server_default="warning", nullable=False),
        sa.Column("last_successful_sync", sa.DateTime(timezone=True)),
        sa.Column("next_scheduled_sync", sa.DateTime(timezone=True)),
        sa.Column("last_sync_error", sa.String(500)),
        sa.Column("last_sync_metadata", sa.JSON()),
        sa.UniqueConstraint("country_code", "region_code", name="uq_holiday_source_country_region"),
    )
    op.create_index("ix_holiday_source_enabled", "platform_holiday_sources", ["enabled"])
    op.create_table(
        "platform_holiday_dates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_id", sa.UUID(), sa.ForeignKey("platform_holiday_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_holiday_id", sa.String(180), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("observed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "source_holiday_id", name="uq_holiday_date_source_key"),
    )
    op.create_index("ix_holiday_date_source_date", "platform_holiday_dates", ["source_id", "holiday_date"])
    op.create_table(
        "home_calendar_highlight_settings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("group_id", sa.UUID(), sa.ForeignKey("groups.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("birthdays_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "home_holiday_subscriptions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("group_id", sa.UUID(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.UUID(), sa.ForeignKey("platform_holiday_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.UniqueConstraint("group_id", "source_id", name="uq_home_holiday_subscription"),
    )
    op.create_index("ix_home_holiday_subscription_home_enabled", "home_holiday_subscriptions", ["group_id", "enabled"])
    sources = sa.table(
        "platform_holiday_sources",
        sa.column("id", sa.UUID()), sa.column("country_code", sa.String()), sa.column("country_name", sa.String()),
        sa.column("flag_emoji", sa.String()), sa.column("region_code", sa.String()), sa.column("region_name", sa.String()),
        sa.column("provider", sa.String()), sa.column("source_url", sa.String()),
    )
    import uuid
    rows = [
        ("GB", "United Kingdom", "🇬🇧", "england-wales", "England & Wales", "GOV.UK", "https://www.gov.uk/bank-holidays"),
        ("GB", "United Kingdom", "🇬🇧", "scotland", "Scotland", "GOV.UK", "https://www.gov.uk/bank-holidays"),
        ("GB", "United Kingdom", "🇬🇧", "northern-ireland", "Northern Ireland", "GOV.UK", "https://www.gov.uk/bank-holidays"),
        ("ZA", "South Africa", "🇿🇦", None, "National holidays", "South African Government", "https://www.gov.za/about-sa/public-holidays"),
        ("US", "United States", "🇺🇸", None, "Federal holidays", "U.S. Office of Personnel Management", "https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/"),
    ]
    op.bulk_insert(sources, [{"id": uuid.uuid4(), "country_code": a, "country_name": b, "flag_emoji": c, "region_code": d, "region_name": e, "provider": f, "source_url": g} for a, b, c, d, e, f, g in rows])


def downgrade() -> None:
    op.drop_index("ix_home_holiday_subscription_home_enabled", table_name="home_holiday_subscriptions")
    op.drop_table("home_holiday_subscriptions")
    op.drop_table("home_calendar_highlight_settings")
    op.drop_index("ix_holiday_date_source_date", table_name="platform_holiday_dates")
    op.drop_table("platform_holiday_dates")
    op.drop_index("ix_holiday_source_enabled", table_name="platform_holiday_sources")
    op.drop_table("platform_holiday_sources")
