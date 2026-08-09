"""Add a profile avatar reference to users. Deliberately just a filename/reference and
a timestamp — the image bytes themselves live on disk under the avatar storage
directory (see mykhaya/avatars/), never in the database. Nullable so existing users
with no avatar continue to work unchanged (initials avatar is the fallback).

Revision ID: 0013_user_avatar
Revises: 0012_template_versioning
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_avatar"
down_revision: str | None = "0012_template_versioning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_key", sa.String(length=64), nullable=True))
    op.add_column(
        "users", sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_updated_at")
    op.drop_column("users", "avatar_key")
