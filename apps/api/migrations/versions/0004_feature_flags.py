"""Add platform memberships and feature flag framework."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_feature_flags"
down_revision: str | None = "0003_calendar_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FEATURE_FLAGS: list[dict[str, str | bool]] = [
    {
        "key": "calendar",
        "display_name": "Calendar",
        "description": "Shared family scheduling and reminders.",
        "enabled": False,
    },
    {
        "key": "tasks",
        "display_name": "Tasks",
        "description": "Household tasks and completion tracking.",
        "enabled": False,
    },
    {
        "key": "shopping",
        "display_name": "Shopping",
        "description": "Shared shopping lists for your Home.",
        "enabled": False,
    },
    {
        "key": "meals",
        "display_name": "Meals",
        "description": "Meal planning and prep coordination.",
        "enabled": False,
    },
    {
        "key": "plans",
        "display_name": "Plans",
        "description": "Longer-term planning tools for families.",
        "enabled": False,
    },
    {
        "key": "wish_lists",
        "display_name": "Wish Lists",
        "description": "Shared wish lists for events and gifting.",
        "enabled": False,
    },
    {
        "key": "notifications",
        "display_name": "Notifications",
        "description": "Delivery controls for important updates.",
        "enabled": False,
    },
    {
        "key": "external_sharing",
        "display_name": "External Sharing",
        "description": "Controlled sharing outside the Home.",
        "enabled": False,
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    platform_role = postgresql.ENUM(
        "owner",
        "administrator",
        "support_operator",
        "read_only_operator",
        name="platform_role",
        create_type=False,
    )
    feature_flag_key = postgresql.ENUM(
        "calendar",
        "tasks",
        "shopping",
        "meals",
        "plans",
        "wish_lists",
        "notifications",
        "external_sharing",
        name="feature_key",
        create_type=False,
    )
    platform_role.create(bind, checkfirst=True)
    feature_flag_key.create(bind, checkfirst=True)
    for value in ("owner", "administrator", "support_operator", "read_only_operator"):
        op.execute(sa.text(f"ALTER TYPE platform_role ADD VALUE IF NOT EXISTS '{value}'"))

    existing_tables = set(inspector.get_table_names())

    if "platform_memberships" not in existing_tables:
        op.create_table(
            "platform_memberships",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", platform_role, nullable=False),
            sa.UniqueConstraint("user_id", name="uq_platform_membership_user"),
        )
    membership_indexes = {row["name"] for row in inspector.get_indexes("platform_memberships")}
    if "ix_platform_memberships_user_id" not in membership_indexes:
        op.create_index("ix_platform_memberships_user_id", "platform_memberships", ["user_id"])
    if "ix_platform_membership_role" not in membership_indexes:
        op.create_index("ix_platform_membership_role", "platform_memberships", ["role"])

    if "feature_flags" not in existing_tables:
        op.create_table(
            "feature_flags",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("key", feature_flag_key, nullable=False),
            sa.Column("display_name", sa.String(80), nullable=False),
            sa.Column("description", sa.String(300), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column(
                "updated_by_platform_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
            ),
            sa.UniqueConstraint("key", name="uq_feature_flag_key"),
        )
    else:
        feature_columns = {
            row["name"] for row in inspector.get_columns("feature_flags")
        }
        if "display_name" not in feature_columns:
            op.add_column(
                "feature_flags",
                sa.Column("display_name", sa.String(80), nullable=True),
            )
        if "description" not in feature_columns:
            op.add_column(
                "feature_flags",
                sa.Column("description", sa.String(300), nullable=True),
            )
        if "updated_by_platform_user_id" not in feature_columns:
            op.add_column(
                "feature_flags",
                sa.Column(
                    "updated_by_platform_user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
        op.execute(
            sa.text(
                """
                UPDATE feature_flags
                SET display_name = INITCAP(REPLACE(key::text, '_', ' '))
                WHERE display_name IS NULL
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE feature_flags
                SET description = 'Feature availability control'
                WHERE description IS NULL
                """
            )
        )
        op.alter_column("feature_flags", "display_name", existing_type=sa.String(80), nullable=False)
        op.alter_column("feature_flags", "description", existing_type=sa.String(300), nullable=False)
    feature_indexes = {row["name"] for row in inspector.get_indexes("feature_flags")}
    if "ix_feature_flag_enabled" not in feature_indexes:
        op.create_index("ix_feature_flag_enabled", "feature_flags", ["enabled"])

    if "feature_flag_home_overrides" not in existing_tables:
        op.create_table(
            "feature_flag_home_overrides",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "feature_flag_id",
                sa.Uuid(),
                sa.ForeignKey("feature_flags.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column(
                "updated_by_platform_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
            ),
            sa.UniqueConstraint("feature_flag_id", "group_id", name="uq_feature_override_home_flag"),
        )
    override_indexes = {
        row["name"] for row in inspector.get_indexes("feature_flag_home_overrides")
    }
    if "ix_feature_flag_home_overrides_feature_flag_id" not in override_indexes:
        op.create_index(
            "ix_feature_flag_home_overrides_feature_flag_id",
            "feature_flag_home_overrides",
            ["feature_flag_id"],
        )
    if "ix_feature_flag_home_overrides_group_id" not in override_indexes:
        op.create_index(
            "ix_feature_flag_home_overrides_group_id",
            "feature_flag_home_overrides",
            ["group_id"],
        )
    if "ix_feature_override_group" not in override_indexes:
        op.create_index("ix_feature_override_group", "feature_flag_home_overrides", ["group_id"])

    key_enum_name = bind.execute(
        sa.text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_name = 'feature_flags' AND column_name = 'key'
            """
        )
    ).scalar_one()
    now = datetime.now(UTC)
    insert_sql = sa.text(
        f"""
        INSERT INTO feature_flags
            (id, created_at, updated_at, key, display_name, description, enabled)
        SELECT
            :id,
            :created_at,
            :updated_at,
            CAST(:key AS text)::{key_enum_name},
            :display_name,
            :description,
            :enabled
        WHERE NOT EXISTS (
            SELECT 1 FROM feature_flags WHERE key::text = :key
        )
        """
    )
    for row in FEATURE_FLAGS:
        bind.execute(
            insert_sql,
            {
                "id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
                "key": row["key"],
                "display_name": row["display_name"],
                "description": row["description"],
                "enabled": row["enabled"],
            },
        )


def downgrade() -> None:
    op.drop_index("ix_feature_override_group", table_name="feature_flag_home_overrides")
    op.drop_index("ix_feature_flag_home_overrides_group_id", table_name="feature_flag_home_overrides")
    op.drop_index("ix_feature_flag_home_overrides_feature_flag_id", table_name="feature_flag_home_overrides")
    op.drop_table("feature_flag_home_overrides")

    op.drop_index("ix_feature_flag_enabled", table_name="feature_flags")
    op.drop_table("feature_flags")

    op.drop_index("ix_platform_membership_role", table_name="platform_memberships")
    op.drop_index("ix_platform_memberships_user_id", table_name="platform_memberships")
    op.drop_table("platform_memberships")

    postgresql.ENUM(name="feature_key").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="platform_role").drop(op.get_bind(), checkfirst=True)
