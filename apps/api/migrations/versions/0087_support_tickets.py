"""Add the MyKhaya Support ticket foundation (Phase 2A): support_tickets,
support_ticket_messages, support_ticket_attachments,
support_ticket_diagnostics, a dedicated MK-#### reference sequence, and the
new FeatureKey.support platform enum value. The FeatureFlag row for
'support' is inserted separately (0088_support_disabled_by_default),
mirroring the 0079/0081 Budget precedent: PostgreSQL will not let a
newly-added enum value be used until the transaction that added it has
committed, and this codebase's established convention keeps that a distinct,
later migration rather than relying on same-migration visibility."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0087_support_tickets"
down_revision: str | None = "0086_budget_spending_entry_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPPORT_REFERENCE_SEQUENCE = "support_ticket_reference_seq"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE feature_key ADD VALUE IF NOT EXISTS 'support'")

    op.execute(
        f"CREATE SEQUENCE IF NOT EXISTS {SUPPORT_REFERENCE_SEQUENCE} "
        "START WITH 1001 INCREMENT BY 1"
    )

    support_ticket_type = postgresql.ENUM(
        "bug", "support", "feedback", name="support_ticket_type"
    )
    support_ticket_status = postgresql.ENUM(
        "open", "in_progress", "waiting_for_user", "resolved", "closed",
        name="support_ticket_status",
    )
    support_ticket_priority = postgresql.ENUM(
        "normal", "elevated", "blocking", name="support_ticket_priority"
    )
    support_ticket_source = postgresql.ENUM(
        "ios", "android", "web", "desktop_web", name="support_ticket_source"
    )
    support_ticket_app_area = postgresql.ENUM(
        "home", "calendar", "family", "nudges", "lists", "meals", "budget",
        "account", "notifications", "more", "other", name="support_ticket_app_area",
    )
    support_message_visibility = postgresql.ENUM(
        "requester", "internal", name="support_message_visibility"
    )
    for enum in (
        support_ticket_type,
        support_ticket_status,
        support_ticket_priority,
        support_ticket_source,
        support_ticket_app_area,
        support_message_visibility,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("requester_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.UUID(), sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", postgresql.ENUM("bug", "support", "feedback", name="support_ticket_type", create_type=False), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open", "in_progress", "waiting_for_user", "resolved", "closed",
                name="support_ticket_status", create_type=False,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "priority",
            postgresql.ENUM("normal", "elevated", "blocking", name="support_ticket_priority", create_type=False),
            server_default="normal",
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("source", postgresql.ENUM("ios", "android", "web", "desktop_web", name="support_ticket_source", create_type=False), nullable=False),
        sa.Column(
            "app_area",
            postgresql.ENUM(
                "home", "calendar", "family", "nudges", "lists", "meals", "budget",
                "account", "notifications", "more", "other",
                name="support_ticket_app_area", create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_admin_id", sa.UUID(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("reference", name="uq_support_tickets_reference"),
    )
    op.create_index("ix_support_tickets_reference", "support_tickets", ["reference"])
    op.create_index("ix_support_tickets_requester_user_id", "support_tickets", ["requester_user_id"])
    op.create_index("ix_support_tickets_group_id", "support_tickets", ["group_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index("ix_support_tickets_assigned_admin_id", "support_tickets", ["assigned_admin_id"])

    op.create_table(
        "support_ticket_messages",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ticket_id", sa.UUID(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_admin_id", sa.UUID(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message", sa.String(length=4000), nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM("requester", "internal", name="support_message_visibility", create_type=False),
            server_default="requester",
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT (author_user_id IS NOT NULL AND author_admin_id IS NOT NULL)",
            name="ck_support_message_single_author",
        ),
    )
    op.create_index("ix_support_ticket_messages_ticket_id", "support_ticket_messages", ["ticket_id"])

    op.create_table(
        "support_ticket_attachments",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ticket_id", sa.UUID(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(length=120), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_by_admin_id", sa.UUID(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("storage_key", name="uq_support_ticket_attachments_storage_key"),
    )
    op.create_index("ix_support_ticket_attachments_ticket_id", "support_ticket_attachments", ["ticket_id"])

    op.create_table(
        "support_ticket_diagnostics",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ticket_id", sa.UUID(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("build_number", sa.String(length=40), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("os_version", sa.String(length=40), nullable=True),
        sa.Column("runtime", sa.String(length=20), nullable=True),
        sa.Column("notification_permission", sa.String(length=20), nullable=True),
        sa.Column("push_registration_state", sa.String(length=20), nullable=True),
        sa.Column("api_connectivity", sa.String(length=20), nullable=True),
        sa.Column("network_state", sa.String(length=20), nullable=True),
        sa.Column("background_refresh_state", sa.String(length=20), nullable=True),
        sa.Column("client_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ticket_id", name="uq_support_ticket_diagnostics_ticket_id"),
    )
    op.create_index("ix_support_ticket_diagnostics_ticket_id", "support_ticket_diagnostics", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("support_ticket_diagnostics")
    op.drop_table("support_ticket_attachments")
    op.drop_table("support_ticket_messages")
    op.drop_table("support_tickets")
    sa.Enum(name="support_message_visibility").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="support_ticket_app_area").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="support_ticket_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="support_ticket_priority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="support_ticket_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="support_ticket_type").drop(op.get_bind(), checkfirst=True)
    op.execute(f"DROP SEQUENCE IF EXISTS {SUPPORT_REFERENCE_SEQUENCE}")
    # PostgreSQL enum values cannot be removed safely. The feature_key value
    # remains harmless and the next migration can continue from this state.
