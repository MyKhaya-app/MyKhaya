"""Add Phase 4 PCC privacy request and subprocessor records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0101_compliance_phase4"
down_revision: str | None = "0100_legal_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    privacy_request_type = postgresql.ENUM(
        "subject_access",
        "rectification",
        "erasure",
        "restriction",
        "objection",
        "data_portability",
        "other",
        name="privacy_request_type",
        create_type=False,
    )
    privacy_request_status = postgresql.ENUM(
        "received",
        "identity_check",
        "in_progress",
        "awaiting_user",
        "completed",
        "declined",
        name="privacy_request_status",
        create_type=False,
    )
    privacy_identity_status = postgresql.ENUM(
        "pending",
        "verified",
        "failed",
        name="privacy_identity_status",
        create_type=False,
    )
    subprocessor_state = postgresql.ENUM(
        "active",
        "inactive",
        "configuration_dependent",
        name="subprocessor_state",
        create_type=False,
    )
    for enum in (
        privacy_request_type,
        privacy_request_status,
        privacy_identity_status,
        subprocessor_state,
    ):
        enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "privacy_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_type", privacy_request_type, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "identity_status", privacy_identity_status, server_default="pending", nullable=False
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", privacy_request_status, server_default="received", nullable=False),
        sa.Column("assigned_administrator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["assigned_administrator_id"], ["platform_administrators.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_privacy_requests_reference"),
    )
    op.create_index("ix_privacy_requests_status_due", "privacy_requests", ["status", "due_date"])
    op.create_index("ix_privacy_requests_user_id", "privacy_requests", ["user_id"])
    op.create_table(
        "subprocessors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(160), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("data_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_location", sa.String(160), nullable=True),
        sa.Column("international_transfer", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("transfer_mechanism", sa.String(300), nullable=True),
        sa.Column("dpa_status", sa.String(80), nullable=True),
        sa.Column("privacy_url", sa.String(500), nullable=True),
        sa.Column(
            "state", subprocessor_state, server_default="configuration_dependent", nullable=False
        ),
        sa.Column("last_reviewed_at", sa.Date(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", name="uq_subprocessors_provider"),
    )


def downgrade() -> None:
    op.drop_table("subprocessors")
    op.drop_index("ix_privacy_requests_user_id", table_name="privacy_requests")
    op.drop_index("ix_privacy_requests_status_due", table_name="privacy_requests")
    op.drop_table("privacy_requests")
    for name in (
        "subprocessor_state",
        "privacy_identity_status",
        "privacy_request_status",
        "privacy_request_type",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
