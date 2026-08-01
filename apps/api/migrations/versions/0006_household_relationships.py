"""Separate household relationships, permissions, child profiles and guardians."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_household_relationships"
down_revision: str | None = "0005_platform_role_enum_compat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

relationship = postgresql.ENUM(
    "home_admin",
    "partner",
    "child",
    "extended_family",
    "friend",
    "review_required",
    name="household_relationship",
    create_type=False,
)
permission_profile = postgresql.ENUM(
    "home_admin",
    "standard_partner",
    "child_restricted",
    "explicit_sharing",
    "review_required",
    name="permission_profile",
    create_type=False,
)
age_band = postgresql.ENUM(
    "under_13", "age_13_15", "age_16_17", name="child_age_band", create_type=False
)
transition_status = postgresql.ENUM(
    "child", "review_due", "converted", name="child_transition_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "home_admin",
        "partner",
        "child",
        "extended_family",
        "friend",
        "review_required",
        name="household_relationship",
    ).create(bind)
    postgresql.ENUM(
        "home_admin",
        "standard_partner",
        "child_restricted",
        "explicit_sharing",
        "review_required",
        name="permission_profile",
    ).create(bind)
    postgresql.ENUM(
        "under_13", "age_13_15", "age_16_17", name="child_age_band"
    ).create(bind)
    postgresql.ENUM(
        "child", "review_due", "converted", name="child_transition_status"
    ).create(bind)

    op.add_column("group_memberships", sa.Column("relationship", relationship))
    op.add_column("group_memberships", sa.Column("permission_profile", permission_profile))
    op.add_column(
        "group_memberships",
        sa.Column(
            "permission_overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "group_memberships",
        sa.Column(
            "shared_resources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Only legacy administrative authority is safe to infer. Personal relationships are not.
    op.execute(
        """
        UPDATE group_memberships
        SET relationship = CASE
              WHEN role IN ('owner', 'administrator') THEN 'home_admin'::household_relationship
              ELSE 'review_required'::household_relationship
            END,
            permission_profile = CASE
              WHEN role IN ('owner', 'administrator') THEN 'home_admin'::permission_profile
              ELSE 'review_required'::permission_profile
            END
        """
    )
    op.alter_column("group_memberships", "relationship", nullable=False)
    op.alter_column("group_memberships", "permission_profile", nullable=False)
    op.create_index(
        "ix_membership_group_relationship", "group_memberships", ["group_id", "relationship"]
    )

    op.add_column("group_invitations", sa.Column("relationship", relationship))
    op.add_column("group_invitations", sa.Column("permission_profile", permission_profile))
    op.add_column(
        "group_invitations",
        sa.Column(
            "shared_resources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE group_invitations
        SET relationship = CASE
              WHEN role IN ('owner', 'administrator') THEN 'home_admin'::household_relationship
              ELSE 'review_required'::household_relationship
            END,
            permission_profile = CASE
              WHEN role IN ('owner', 'administrator') THEN 'home_admin'::permission_profile
              ELSE 'review_required'::permission_profile
            END
        """
    )
    op.alter_column("group_invitations", "relationship", nullable=False)
    op.alter_column("group_invitations", "permission_profile", nullable=False)

    op.add_column(
        "feature_overrides",
        sa.Column(
            "updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
    )

    op.create_table(
        "child_profiles",
        sa.Column(
            "membership_id",
            sa.Uuid(),
            sa.ForeignKey("group_memberships.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("age_band", age_band, nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "transition_status",
            transition_status,
            nullable=False,
            server_default="child",
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_child_profiles_membership_id", "child_profiles", ["membership_id"])
    op.create_table(
        "guardian_assignments",
        sa.Column(
            "child_profile_id",
            sa.Uuid(),
            sa.ForeignKey("child_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guardian_membership_id",
            sa.Uuid(),
            sa.ForeignKey("group_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "child_profile_id", "guardian_membership_id", name="uq_child_guardian"
        ),
    )
    op.create_index(
        "ix_guardian_assignments_child_profile_id",
        "guardian_assignments",
        ["child_profile_id"],
    )
    op.create_index(
        "ix_guardian_assignments_guardian_membership_id",
        "guardian_assignments",
        ["guardian_membership_id"],
    )


def downgrade() -> None:
    op.drop_table("guardian_assignments")
    op.drop_table("child_profiles")
    op.drop_column("feature_overrides", "updated_by_user_id")
    op.drop_column("group_invitations", "shared_resources")
    op.drop_column("group_invitations", "permission_profile")
    op.drop_column("group_invitations", "relationship")
    op.drop_index("ix_membership_group_relationship", table_name="group_memberships")
    op.drop_column("group_memberships", "shared_resources")
    op.drop_column("group_memberships", "permission_overrides")
    op.drop_column("group_memberships", "permission_profile")
    op.drop_column("group_memberships", "relationship")
    bind = op.get_bind()
    postgresql.ENUM(name="child_transition_status").drop(bind)
    postgresql.ENUM(name="child_age_band").drop(bind)
    postgresql.ENUM(name="permission_profile").drop(bind)
    postgresql.ENUM(name="household_relationship").drop(bind)
