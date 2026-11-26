"""Store additional non-sensitive DVLA vehicle specifications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0130_driveway_provider_fields"
down_revision: str | None = "0129_beta_enrollment_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        ("co2_emissions", sa.Integer()),
        ("euro_status", sa.String(40)),
        ("type_approval", sa.String(20)),
        ("wheel_plan", sa.String(80)),
        ("revenue_weight", sa.Integer()),
        ("marked_for_export", sa.Boolean()),
        ("marked_as_scrapped", sa.Boolean()),
        ("date_of_last_v5c_issued", sa.Date()),
        ("real_driving_emissions", sa.String(40)),
        ("vehicle_status", sa.String(40)),
        ("automated_vehicle", sa.Boolean()),
        ("art_end_date", sa.Date()),
    )
    for name, column_type in columns:
        op.add_column("vehicles", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in (
        "art_end_date",
        "automated_vehicle",
        "vehicle_status",
        "real_driving_emissions",
        "date_of_last_v5c_issued",
        "marked_as_scrapped",
        "marked_for_export",
        "revenue_weight",
        "wheel_plan",
        "type_approval",
        "euro_status",
        "co2_emissions",
    ):
        op.drop_column("vehicles", name)
