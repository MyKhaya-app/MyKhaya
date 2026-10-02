"""Add explicitly enrolled consumer MFA methods and email challenges.

This is additive. Existing users have no enrolled methods and remain unaffected
while browser_mfa_handoff_enabled is false.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069_consumer_mfa"
down_revision: str | None = "0068_external_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MFA_METHOD = postgresql.ENUM("totp", "email", name="user_mfa_method", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _MFA_METHOD.create(bind)
    op.create_table(
        "user_mfa_methods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("method", _MFA_METHOD, nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "method", name="uq_user_mfa_method"),
    )
    op.create_index(
        "ix_user_mfa_methods_user_active", "user_mfa_methods", ["user_id", "enabled"]
    )
    op.create_table(
        "mfa_email_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_reference_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mfa_email_challenges_transaction",
        "mfa_email_challenges",
        ["transaction_reference_hash"],
    )
    op.create_index(
        "ix_mfa_email_challenges_user_created", "mfa_email_challenges", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_email_challenges_user_created", table_name="mfa_email_challenges")
    op.drop_index("ix_mfa_email_challenges_transaction", table_name="mfa_email_challenges")
    op.drop_table("mfa_email_challenges")
    op.drop_index("ix_user_mfa_methods_user_active", table_name="user_mfa_methods")
    op.drop_table("user_mfa_methods")
    _MFA_METHOD.drop(op.get_bind())
