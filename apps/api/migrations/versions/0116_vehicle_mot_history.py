"""Driveway MOT Phase 1: persisted MOT summary state and normalised history.

Additive only: four nullable cache columns on ``vehicles`` and two new tables
(``vehicle_mot_tests``, ``vehicle_mot_defects``). No existing column, value,
constraint or index changes; no data is written. Downgrade drops exactly what
this adds (the dropped data is re-fetchable provider cache)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0116_vehicle_mot_history"
down_revision: str | None = "0115_vehicle_ciphertext"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("mot_first_due_date", sa.Date(), nullable=True))
    op.add_column(
        "vehicles", sa.Column("mot_refreshed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "vehicles",
        sa.Column("mot_refresh_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("vehicles", sa.Column("mot_refresh_outcome", sa.String(30), nullable=True))

    op.create_table(
        "vehicle_mot_tests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "vehicle_id",
            sa.Uuid(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("test_number", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("odometer_value", sa.Integer(), nullable=True),
        sa.Column("odometer_unit", sa.String(4), nullable=True),
        sa.Column("odometer_result", sa.String(20), nullable=True),
    )
    op.create_index("ix_vehicle_mot_tests_group_id", "vehicle_mot_tests", ["group_id"])
    op.create_index(
        "ix_vehicle_mot_tests_vehicle_date", "vehicle_mot_tests", ["vehicle_id", "test_date"]
    )
    op.create_index(
        "uq_vehicle_mot_tests_provider_number",
        "vehicle_mot_tests",
        ["vehicle_id", "provider", "test_number"],
        unique=True,
        postgresql_where=sa.text("test_number IS NOT NULL"),
    )

    op.create_table(
        "vehicle_mot_defects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "mot_test_id",
            sa.Uuid(),
            sa.ForeignKey("vehicle_mot_tests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("dangerous", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_vehicle_mot_defects_mot_test_id", "vehicle_mot_defects", ["mot_test_id"])


def downgrade() -> None:
    op.drop_index("ix_vehicle_mot_defects_mot_test_id", table_name="vehicle_mot_defects")
    op.drop_table("vehicle_mot_defects")
    op.drop_index("uq_vehicle_mot_tests_provider_number", table_name="vehicle_mot_tests")
    op.drop_index("ix_vehicle_mot_tests_vehicle_date", table_name="vehicle_mot_tests")
    op.drop_index("ix_vehicle_mot_tests_group_id", table_name="vehicle_mot_tests")
    op.drop_table("vehicle_mot_tests")
    op.drop_column("vehicles", "mot_refresh_outcome")
    op.drop_column("vehicles", "mot_refresh_attempted_at")
    op.drop_column("vehicles", "mot_refreshed_at")
    op.drop_column("vehicles", "mot_first_due_date")
