"""Add processed vehicle photos."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0097_vehicle_photos"
down_revision: str | None = "0096_driveway_lookup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("photo_key", sa.String(120)))
    op.add_column("vehicles", sa.Column("photo_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("vehicles", "photo_updated_at")
    op.drop_column("vehicles", "photo_key")
