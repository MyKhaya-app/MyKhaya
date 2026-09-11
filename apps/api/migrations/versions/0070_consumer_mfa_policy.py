"""Add consumer MFA policy hierarchy fields."""

from alembic import op
import sqlalchemy as sa

revision = "0070_consumer_mfa_policy"
down_revision = "0069_consumer_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sa.Enum("inherit", "optional", "required", name="consumer_mfa_policy").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_policy",
            sa.Enum("inherit", "optional", "required", name="consumer_mfa_policy", create_type=False),
            nullable=False,
            server_default="inherit",
        ),
    )
    op.add_column("users", sa.Column("mfa_allowed_methods", sa.JSON(), nullable=True))
    op.add_column(
        "groups",
        sa.Column(
            "mfa_policy",
            sa.Enum("inherit", "optional", "required", name="consumer_mfa_policy", create_type=False),
            nullable=False,
            server_default="inherit",
        ),
    )
    op.add_column("groups", sa.Column("mfa_allowed_methods", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("groups", "mfa_allowed_methods")
    op.drop_column("groups", "mfa_policy")
    op.drop_column("users", "mfa_allowed_methods")
    op.drop_column("users", "mfa_policy")
    op.execute("DROP TYPE consumer_mfa_policy")
