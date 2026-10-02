"""Store processed Meal image references as opaque media keys."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099_meal_image_keys"
down_revision: str | None = "0098_budget_fixed_item_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meals", sa.Column("image_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("meals", "image_key")
