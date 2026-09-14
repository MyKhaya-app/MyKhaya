"""Add reusable Lists templates and copied list sections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0072_list_templates"
down_revision: str | None = "0071_calendar_highlights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "list_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("scope", sa.Enum("personal", "household", name="routine_scope", create_type=False), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_list_template_name_nonempty"),
    )
    op.create_index("ix_list_templates_group_id", "list_templates", ["group_id"])
    op.create_index("ix_list_templates_owner_user_id", "list_templates", ["owner_user_id"])
    op.create_index("ix_list_template_home_scope_active", "list_templates", ["group_id", "scope", "archived_at"])

    op.create_table(
        "list_template_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("list_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_list_template_sections_template_id", "list_template_sections", ["template_id"])
    op.create_index("ix_list_template_section_template_position", "list_template_sections", ["template_id", "position"])

    op.create_table(
        "list_template_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("section_id", sa.Uuid(), sa.ForeignKey("list_template_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("char_length(text) >= 1", name="ck_list_template_item_text_nonempty"),
    )
    op.create_index("ix_list_template_items_section_id", "list_template_items", ["section_id"])
    op.create_index("ix_list_template_item_section_position", "list_template_items", ["section_id", "position"])

    op.create_table(
        "household_list_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("list_id", sa.Uuid(), sa.ForeignKey("household_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_household_list_sections_list_id", "household_list_sections", ["list_id"])
    op.create_index("ix_household_list_section_list_position", "household_list_sections", ["list_id", "position"])

    op.add_column("household_lists", sa.Column("source_template_id", sa.Uuid(), nullable=True))
    op.add_column("household_lists", sa.Column("source_template_name", sa.String(160), nullable=True))
    op.create_foreign_key(
        "fk_household_lists_source_template", "household_lists", "list_templates", ["source_template_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_household_lists_source_template_id", "household_lists", ["source_template_id"])
    op.add_column("household_list_items", sa.Column("section_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_household_list_items_section", "household_list_items", "household_list_sections", ["section_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_household_list_items_section_id", "household_list_items", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_household_list_items_section_id", table_name="household_list_items")
    op.drop_constraint("fk_household_list_items_section", "household_list_items", type_="foreignkey")
    op.drop_column("household_list_items", "section_id")
    op.drop_index("ix_household_lists_source_template_id", table_name="household_lists")
    op.drop_constraint("fk_household_lists_source_template", "household_lists", type_="foreignkey")
    op.drop_column("household_lists", "source_template_name")
    op.drop_column("household_lists", "source_template_id")
    op.drop_index("ix_household_list_section_list_position", table_name="household_list_sections")
    op.drop_index("ix_household_list_sections_list_id", table_name="household_list_sections")
    op.drop_table("household_list_sections")
    op.drop_index("ix_list_template_item_section_position", table_name="list_template_items")
    op.drop_index("ix_list_template_items_section_id", table_name="list_template_items")
    op.drop_table("list_template_items")
    op.drop_index("ix_list_template_section_template_position", table_name="list_template_sections")
    op.drop_index("ix_list_template_sections_template_id", table_name="list_template_sections")
    op.drop_table("list_template_sections")
    op.drop_index("ix_list_template_home_scope_active", table_name="list_templates")
    op.drop_index("ix_list_templates_owner_user_id", table_name="list_templates")
    op.drop_index("ix_list_templates_group_id", table_name="list_templates")
    op.drop_table("list_templates")
