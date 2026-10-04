"""Add the Legal & Compliance foundation (Phase 1): legal_documents,
legal_document_versions, legal_acceptances.

New feature, entirely additive — no existing table or column is touched.
LegalDocument.key is a plain string (not a DB enum) so future document
types can be added by inserting a row, never by migration. LegalDocument
rows for terms/privacy/children_privacy/cookies are NOT seeded here; seeding
draft content is Phase 5, and no version is ever auto-published by a
migration (see the Legal & Compliance brief: "An authorised PCC
administrator must review and explicitly publish the first production
versions").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0100_legal_documents"
down_revision: str | None = "0099_meal_image_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    legal_audience = postgresql.ENUM("adult", "child", name="legal_audience")
    legal_action_verb = postgresql.ENUM("accept", "acknowledge", name="legal_action_verb")
    legal_document_version_status = postgresql.ENUM(
        "draft", "scheduled", "published", "superseded", name="legal_document_version_status"
    )
    legal_reacceptance_scope = postgresql.ENUM(
        "none", "new_users_only", "all_existing_users", name="legal_reacceptance_scope"
    )
    legal_record_type = postgresql.ENUM(
        "user_acceptance",
        "user_acknowledgement",
        "guardian_authorisation",
        "child_notice_acknowledgement",
        name="legal_record_type",
    )
    legal_acceptance_context = postgresql.ENUM(
        "signup",
        "login_reauth",
        "policy_update",
        "subscription_purchase",
        "settings",
        "guardian_child_login_setup",
        "child_login_session",
        name="legal_acceptance_context",
    )
    legal_platform = postgresql.ENUM("web", "ios", "android", name="legal_platform")
    for enum in (
        legal_audience,
        legal_action_verb,
        legal_document_version_status,
        legal_reacceptance_scope,
        legal_record_type,
        legal_acceptance_context,
        legal_platform,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "legal_documents",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "audience",
            postgresql.ENUM("adult", "child", name="legal_audience", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "action_verb",
            postgresql.ENUM("accept", "acknowledge", name="legal_action_verb", create_type=False),
            server_default="accept",
            nullable=False,
        ),
        sa.Column("acceptance_required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key", name="uq_legal_documents_key"),
    )

    op.create_table(
        "legal_document_versions",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.UUID(),
            sa.ForeignKey("legal_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "scheduled",
                "published",
                "superseded",
                name="legal_document_version_status",
                create_type=False,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.String(length=2000), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column(
            "reacceptance_scope",
            postgresql.ENUM(
                "none",
                "new_users_only",
                "all_existing_users",
                name="legal_reacceptance_scope",
                create_type=False,
            ),
            server_default="new_users_only",
            nullable=False,
        ),
        sa.Column(
            "created_by_administrator_id",
            sa.UUID(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_administrator_id",
            sa.UUID(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_by_administrator_id",
            sa.UUID(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_version_id", sa.UUID(), nullable=True),
        sa.UniqueConstraint(
            "document_id", "version_sequence", name="uq_legal_document_version_sequence"
        ),
    )
    op.create_foreign_key(
        "fk_legal_document_versions_superseded_by",
        "legal_document_versions",
        "legal_document_versions",
        ["superseded_by_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_legal_document_versions_document_id", "legal_document_versions", ["document_id"]
    )
    op.create_index(
        "ix_legal_document_versions_document_status",
        "legal_document_versions",
        ["document_id", "status"],
    )

    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "record_type",
            postgresql.ENUM(
                "user_acceptance",
                "user_acknowledgement",
                "guardian_authorisation",
                "child_notice_acknowledgement",
                name="legal_record_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            sa.UUID(),
            sa.ForeignKey("legal_document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "child_profile_id",
            sa.UUID(),
            sa.ForeignKey("child_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "context",
            postgresql.ENUM(
                "signup",
                "login_reauth",
                "policy_update",
                "subscription_purchase",
                "settings",
                "guardian_child_login_setup",
                "child_login_session",
                name="legal_acceptance_context",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "platform",
            postgresql.ENUM("web", "ios", "android", name="legal_platform", create_type=False),
            nullable=False,
        ),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("session_reference", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.CheckConstraint(
            "("
            "  record_type IN ('user_acceptance', 'user_acknowledgement')"
            "  AND user_id IS NOT NULL AND child_profile_id IS NULL"
            ") OR ("
            "  record_type = 'guardian_authorisation'"
            "  AND user_id IS NOT NULL AND child_profile_id IS NOT NULL"
            ") OR ("
            "  record_type = 'child_notice_acknowledgement'"
            "  AND user_id IS NULL AND child_profile_id IS NOT NULL"
            ")",
            name="ck_legal_acceptance_actor_shape",
        ),
    )
    op.create_index(
        "ix_legal_acceptances_document_version_id", "legal_acceptances", ["document_version_id"]
    )
    op.create_index("ix_legal_acceptances_user_id", "legal_acceptances", ["user_id"])
    op.create_index(
        "ix_legal_acceptances_child_profile_id", "legal_acceptances", ["child_profile_id"]
    )


def downgrade() -> None:
    op.drop_table("legal_acceptances")
    op.drop_constraint(
        "fk_legal_document_versions_superseded_by", "legal_document_versions", type_="foreignkey"
    )
    op.drop_table("legal_document_versions")
    op.drop_table("legal_documents")
    sa.Enum(name="legal_platform").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_acceptance_context").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_record_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_reacceptance_scope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_document_version_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_action_verb").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="legal_audience").drop(op.get_bind(), checkfirst=True)
