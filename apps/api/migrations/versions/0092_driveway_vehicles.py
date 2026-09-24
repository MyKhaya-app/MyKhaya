"""Add the Driveway core vehicle model (Phase 2 — no documents/service/
insurance/compliance sub-tables yet, no official-lookup provider state)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0092_driveway_vehicles"
down_revision: str | None = "0091_driveway_disabled_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reuses the existing routine_scope enum (created by migration 0024) verbatim
# — same Personal/Household primitive as ListTemplate.
routine_scope = postgresql.ENUM("personal", "household", name="routine_scope", create_type=False)


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("group_id", sa.UUID(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope", routine_scope, nullable=False),
        sa.Column("nickname", sa.String(120), nullable=False),
        sa.Column("make", sa.String(80)),
        sa.Column("model", sa.String(80)),
        sa.Column("colour", sa.String(40)),
        sa.Column("year", sa.Integer()),
        sa.Column("fuel_type", sa.String(30)),
        sa.Column("engine_size", sa.String(20)),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("registration", sa.String(20)),
        sa.Column("first_registration_date", sa.Date()),
        sa.Column("vin", sa.String(32)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(nickname) >= 1", name="ck_vehicle_nickname_nonempty"),
        sa.CheckConstraint("char_length(country_code) = 2", name="ck_vehicle_country_code_iso2"),
    )
    op.create_index("ix_vehicles_group_id", "vehicles", ["group_id"])
    op.create_index("ix_vehicles_owner_user_id", "vehicles", ["owner_user_id"])
    op.create_index(
        "ix_vehicle_home_scope_active", "vehicles", ["group_id", "scope", "archived_at"]
    )


def downgrade() -> None:
    op.drop_table("vehicles")
