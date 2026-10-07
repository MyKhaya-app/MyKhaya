"""Beta registration records intent only: Home name and Beta Terms are now
collected after email verification, in the authenticated Beta continuation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0114_beta_pending_intent"
down_revision: str | None = "0113_beta_programme_app_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "beta_pending_registrations", "home_name", existing_type=sa.String(100), nullable=True
    )
    op.alter_column(
        "beta_pending_registrations", "terms_version", existing_type=sa.String(80), nullable=True
    )


def downgrade() -> None:
    op.execute("UPDATE beta_pending_registrations SET home_name = '' WHERE home_name IS NULL")
    op.execute(
        "UPDATE beta_pending_registrations SET terms_version = '' WHERE terms_version IS NULL"
    )
    op.alter_column(
        "beta_pending_registrations", "terms_version", existing_type=sa.String(80), nullable=False
    )
    op.alter_column(
        "beta_pending_registrations", "home_name", existing_type=sa.String(100), nullable=False
    )
