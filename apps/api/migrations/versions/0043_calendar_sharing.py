"""Add external Calendar Sharing: `calendar_shares`, one recipient's access to one
calendar outside its own Home — see mykhaya.models.CalendarShare's docstring.

Additive only. No changes to `household_relationship`, `permission_profile`,
`group_memberships`, or `group_invitations` — existing Extended Family/Friend
Home members and their `shared_resources` keep working exactly as before.
`routers.invitations` stops accepting new invitations for those two
relationships going forward (an application-layer change, not a schema one);
existing rows are never touched by this migration.

`calendar_shares` stores no separate token column, matching `wishlist_shares`
and `group_invitations`: the recipient's link token is the HMAC-signed
encoding of the row's own `id` (mykhaya.security.derived_token, purpose
"calendar_share").

Revision ID: 0043_calendar_sharing
Revises: 0042_wishlist_home_visibility
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_calendar_sharing"
down_revision: str | None = "0042_wishlist_home_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

calendar_share_permission = postgresql.ENUM(
    "view",
    "manage",
    name="calendar_share_permission",
    create_type=False,
)
calendar_share_status = postgresql.ENUM(
    "pending_admin_approval",
    "pending_recipient",
    "accepted",
    "declined",
    "revoked",
    name="calendar_share_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    calendar_share_permission.create(bind)
    calendar_share_status.create(bind)

    op.create_table(
        "calendar_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resource_type", sa.String(20), nullable=False, server_default="calendar"),
        sa.Column(
            "calendar_id",
            sa.Uuid(),
            sa.ForeignKey("home_calendars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("permission", calendar_share_permission, nullable=False),
        sa.Column(
            "status", calendar_share_status, nullable=False, server_default="pending_recipient"
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("declined_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("notification_preference", sa.String(20), nullable=False, server_default="all"),
        sa.Column("include_in_briefing", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_calendar_shares_calendar_id", "calendar_shares", ["calendar_id"])
    op.create_index("ix_calendar_shares_source_group_id", "calendar_shares", ["source_group_id"])
    op.create_index(
        "ix_calendar_shares_recipient_user_id", "calendar_shares", ["recipient_user_id"]
    )
    op.create_index(
        "ix_calendar_share_calendar_status", "calendar_shares", ["calendar_id", "status"]
    )
    op.create_index("ix_calendar_share_recipient_email", "calendar_shares", ["recipient_email"])
    op.create_index("ix_calendar_share_recipient_user", "calendar_shares", ["recipient_user_id"])
    op.create_index("ix_calendar_shares_expires_at", "calendar_shares", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_calendar_shares_expires_at", table_name="calendar_shares")
    op.drop_index("ix_calendar_share_recipient_user", table_name="calendar_shares")
    op.drop_index("ix_calendar_share_recipient_email", table_name="calendar_shares")
    op.drop_index("ix_calendar_share_calendar_status", table_name="calendar_shares")
    op.drop_index("ix_calendar_shares_recipient_user_id", table_name="calendar_shares")
    op.drop_index("ix_calendar_shares_source_group_id", table_name="calendar_shares")
    op.drop_index("ix_calendar_shares_calendar_id", table_name="calendar_shares")
    op.drop_table("calendar_shares")

    bind = op.get_bind()
    postgresql.ENUM(name="calendar_share_status").drop(bind)
    postgresql.ENUM(name="calendar_share_permission").drop(bind)
