"""Managed Child sign-in: a Home-scoped code + Child username/PIN, kept entirely
separate from adult email/password authentication. A Child stays the same managed
identity (User + Membership + ChildProfile) it already was — this only adds an
optional, parent-configured credential and marks which kind of principal a Session
authenticates, so no route can accidentally treat a managed Child session as an
ordinary adult's.

- sessions.kind: new session_kind enum ('adult' | 'managed_child'), defaulted and
  backfilled to 'adult' for every existing session (all sessions issued before this
  feature existed were, definitionally, adult sessions).
- groups.child_login_code: a short random per-Home code (see mykhaya.security.
  generate_home_code) a Child types in alongside their username/PIN to identify their
  Home at sign-in without exposing membership or Home names. Backfilled for every
  existing Home so the column can be NOT NULL UNIQUE from the start, not left nullable
  purely to dodge a backfill.
- child_profiles.login_enabled / username_normalised / pin_hash / login_updated_at:
  additive and nullable/false by default — every existing Child profile keeps sign-in
  disabled until an adult explicitly turns it on.

Revision ID: 0016_managed_child_login
Revises: 0015_colour_palette
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_managed_child_login"
down_revision: str | None = "0015_colour_palette"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Excludes visually-confusable characters (0/O, 1/I/L) — a Child is expected to type
# this on a phone keyboard, not paste it. Self-contained here rather than imported
# from mykhaya.security so this migration keeps working unchanged even if that
# module's generator logic changes later.
_HOME_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_home_code() -> str:
    return "".join(secrets.choice(_HOME_CODE_ALPHABET) for _ in range(8))


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("adult", "managed_child", name="session_kind").create(bind)
    op.add_column(
        "sessions",
        sa.Column(
            "kind",
            postgresql.ENUM("adult", "managed_child", name="session_kind", create_type=False),
            nullable=False,
            server_default="adult",
        ),
    )

    op.add_column("groups", sa.Column("child_login_code", sa.String(10), nullable=True))
    group_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM groups")).fetchall()]
    used: set[str] = set()
    for group_id in group_ids:
        code = _generate_home_code()
        while code in used:
            code = _generate_home_code()
        used.add(code)
        bind.execute(
            sa.text("UPDATE groups SET child_login_code = :code WHERE id = :id"),
            {"code": code, "id": group_id},
        )
    op.alter_column("groups", "child_login_code", nullable=False)
    op.create_unique_constraint("uq_groups_child_login_code", "groups", ["child_login_code"])
    op.create_index(
        "ix_groups_child_login_code", "groups", ["child_login_code"], unique=True
    )

    op.add_column(
        "child_profiles",
        sa.Column("login_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "child_profiles", sa.Column("username_normalised", sa.String(32), nullable=True)
    )
    op.add_column("child_profiles", sa.Column("pin_hash", sa.Text(), nullable=True))
    op.add_column(
        "child_profiles",
        sa.Column("login_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("child_profiles", "login_updated_at")
    op.drop_column("child_profiles", "pin_hash")
    op.drop_column("child_profiles", "username_normalised")
    op.drop_column("child_profiles", "login_enabled")

    op.drop_index("ix_groups_child_login_code", table_name="groups")
    op.drop_constraint("uq_groups_child_login_code", "groups", type_="unique")
    op.drop_column("groups", "child_login_code")

    op.drop_column("sessions", "kind")
    bind = op.get_bind()
    postgresql.ENUM(name="session_kind").drop(bind)
