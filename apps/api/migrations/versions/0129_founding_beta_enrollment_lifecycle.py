"""Add explicit Founding Beta enrollment lifecycle states.

Active rows consume capacity. Withdrawn rows preserve the participant's
repeat-claim restriction. Released rows preserve history but no longer retain
the former normalized email association.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0129_beta_enrollment_lifecycle"
down_revision: str | None = "0128_password_setup_purpose"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    status_enum = postgresql.ENUM("active", "withdrawn", "released", name="beta_enrollment_status")
    status_enum.create(bind, checkfirst=True)
    op.add_column(
        "beta_enrollments",
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "beta_enrollments",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "beta_enrollments",
        sa.Column(
            "status_changed_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "beta_enrollments",
        sa.Column("status_reason", sa.String(length=500), nullable=True),
    )
    op.alter_column("beta_enrollments", "normalized_email", nullable=True)
    op.drop_constraint("uq_beta_enrollment_programme_email", "beta_enrollments", type_="unique")
    op.create_index(
        "uq_beta_enrollment_programme_email_retained",
        "beta_enrollments",
        ["programme_id", "normalized_email"],
        unique=True,
        postgresql_where=sa.text("normalized_email IS NOT NULL"),
    )
    op.create_index(
        "ix_beta_enrollment_programme_status",
        "beta_enrollments",
        ["programme_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    incompatible = bind.execute(
        sa.text(
            "SELECT count(*) FROM beta_enrollments "
            "WHERE status <> 'active' OR normalized_email IS NULL"
        )
    ).scalar_one()
    if incompatible:
        raise RuntimeError(
            "0129 cannot be downgraded while withdrawn or released enrollments "
            "exist, or while a normalized email is null. Restore from a "
            "reviewed database backup instead."
        )

    duplicate_checks = (
        (
            sa.text(
                "SELECT 1 FROM beta_enrollments "
                "GROUP BY programme_id, normalized_email HAVING count(*) > 1 LIMIT 1"
            ),
            "retained normalized emails",
        ),
        (
            sa.text(
                "SELECT 1 FROM beta_enrollments "
                "GROUP BY programme_id, joined_user_id HAVING count(*) > 1 LIMIT 1"
            ),
            "programme/user allocations",
        ),
        (
            sa.text(
                "SELECT 1 FROM beta_enrollments "
                "GROUP BY programme_id, home_id HAVING count(*) > 1 LIMIT 1"
            ),
            "programme/Home allocations",
        ),
    )
    for query, label in duplicate_checks:
        duplicate = bind.execute(query).first()
        if duplicate is not None:
            raise RuntimeError(
                f"0129 cannot be downgraded: duplicate {label} would violate the 0128 schema."
            )

    # PostgreSQL DDL is transactional: any failure after this preflight rolls
    # back the complete downgrade, leaving the 0129 schema intact.
    op.drop_index("uq_beta_enrollment_programme_email_retained", table_name="beta_enrollments")
    op.create_unique_constraint(
        "uq_beta_enrollment_programme_email",
        "beta_enrollments",
        ["programme_id", "normalized_email"],
    )
    op.alter_column("beta_enrollments", "normalized_email", nullable=False)
    op.drop_index("ix_beta_enrollment_programme_status", table_name="beta_enrollments")
    for column in ("status_changed_by", "status_reason", "status_changed_at", "status"):
        op.drop_column("beta_enrollments", column)
    postgresql.ENUM(name="beta_enrollment_status").drop(bind, checkfirst=True)
