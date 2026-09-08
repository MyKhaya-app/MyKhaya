"""Add Nudges To-dos and user-created To-do categories.

Revision ID: 0056_nudges_todos
Revises: 0055_user_anonymised_at
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_nudges_todos"
down_revision: str | None = "0055_user_anonymised_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

routine_scope = postgresql.ENUM(
    "personal", "household", name="routine_scope", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "todo_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_todo_category_name_nonempty"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "name", name="uq_todo_category_home_name"),
    )
    op.create_index("ix_todo_category_group", "todo_categories", ["group_id"])
    op.create_table(
        "todos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("scope", routine_scope, nullable=False, server_default="household"),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_todo_title_nonempty"),
        sa.CheckConstraint("(scope = 'personal' AND owner_user_id IS NOT NULL) OR (scope = 'household' AND owner_user_id IS NULL)", name="ck_todo_scope_owner"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["todo_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_todo_group_due", "todos", ["group_id", "due_date"])
    op.create_index("ix_todos_group_id", "todos", ["group_id"])
    op.create_index("ix_todos_owner_user_id", "todos", ["owner_user_id"])
    op.create_index("ix_todos_category_id", "todos", ["category_id"])
    op.create_table(
        "todo_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("todo_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["todo_id"], ["todos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("todo_id", "user_id", name="uq_todo_member"),
    )
    op.create_index("ix_todo_members_todo_id", "todo_members", ["todo_id"])
    op.create_index("ix_todo_members_user_id", "todo_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("todo_members")
    op.drop_index("ix_todo_category_group", table_name="todo_categories")
    op.drop_table("todos")
    op.drop_table("todo_categories")
