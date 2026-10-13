"""Add nullable ciphertext columns for Driveway registration and VIN.

Sensitive Data Protection Phase 2B (dual-write only). Additive: two nullable
TEXT columns, no default, no index, no constraint, no backfill. The existing
plaintext registration/vin columns and their values are untouched and remain
authoritative. Downgrade drops only the new columns (any ciphertext in them is
a redundant copy of the plaintext in this phase)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0115_vehicle_ciphertext"
down_revision: str | None = "0114_beta_pending_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("registration_ciphertext", sa.Text(), nullable=True))
    op.add_column("vehicles", sa.Column("vin_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "vin_ciphertext")
    op.drop_column("vehicles", "registration_ciphertext")
