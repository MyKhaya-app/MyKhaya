"""Showcase Demo Homes: the 'ultimate_demo' managed type and showcase dates.

Adds the Ultimate Demo managed fixture type (complimentary Ultimate access,
seeded by mykhaya.showcase) and three columns recording how a showcase Home
was populated, so a PCC "Reset Showcase Data" can restore exactly that state:

* showcase_populated — False for legacy fixtures and clean engineering Homes.
* showcase_date_mode — "rolling" (relative to the seed day) or "pinned".
* showcase_reference_date — the pinned screenshot reference date.

Existing rows keep their current behaviour: every new column is nullable or
defaults to false, and no existing fixture is reseeded by this migration.

As in 0064_free_demo_managed_type, ALTER TYPE ... ADD VALUE runs in an
autocommit block and nothing here uses the new value.

Revision ID: 0119_showcase_demo_homes
Revises: 0118_driveway_nudge_category
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0119_showcase_demo_homes"
down_revision: str | None = "0118_driveway_nudge_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE managed_demo_type ADD VALUE IF NOT EXISTS 'ultimate_demo'")
    op.add_column(
        "managed_demo_homes",
        sa.Column("showcase_populated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "managed_demo_homes", sa.Column("showcase_date_mode", sa.String(10), nullable=True)
    )
    op.add_column(
        "managed_demo_homes", sa.Column("showcase_reference_date", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("managed_demo_homes", "showcase_reference_date")
    op.drop_column("managed_demo_homes", "showcase_date_mode")
    op.drop_column("managed_demo_homes", "showcase_populated")
    # The enum value is left defined: PostgreSQL has no ALTER TYPE ... DROP
    # VALUE (see 0064_free_demo_managed_type).
