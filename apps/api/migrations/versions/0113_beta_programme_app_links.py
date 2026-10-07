"""Site-wide iPhone/Android app links, managed in PCC's Founding Beta section."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0113_beta_programme_app_links"
down_revision: str | None = "0112_home_migration_packages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("beta_programmes", sa.Column("ios_app_url", sa.String(500), nullable=True))
    op.add_column("beta_programmes", sa.Column("android_app_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("beta_programmes", "android_app_url")
    op.drop_column("beta_programmes", "ios_app_url")
