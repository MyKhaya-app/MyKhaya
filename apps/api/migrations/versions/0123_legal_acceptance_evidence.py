"""Add immutable legal acceptance evidence lifecycle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0123_legal_acceptance_evidence"
down_revision: str | None = "0122_stripe_webhook_ip_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    evidence_status = postgresql.ENUM(
        "pending", "generating", "ready", "sending", "sent", "failed", "retry_pending",
        name="legal_evidence_status",
        create_type=False,
    )
    evidence_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "legal_acceptance_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("registered_email", sa.String(320), nullable=True),
        sa.Column("account_name", sa.String(100), nullable=True),
        sa.Column("document_name", sa.String(200), nullable=False),
        sa.Column("document_version", sa.String(20), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("accepted_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_timezone", sa.String(100), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column(
            "platform",
            postgresql.ENUM("web", "ios", "android", name="legal_platform", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "action_type",
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
        sa.Column("status", evidence_status, server_default="pending", nullable=False),
        sa.Column("pdf_storage_key", sa.String(255), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["acceptance_id"], ["legal_acceptances.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("acceptance_id", name="uq_legal_acceptance_evidence_acceptance"),
    )
    op.create_index("ix_legal_acceptance_evidence_status", "legal_acceptance_evidence", ["status"])


def downgrade() -> None:
    op.drop_index("ix_legal_acceptance_evidence_status", table_name="legal_acceptance_evidence")
    op.drop_table("legal_acceptance_evidence")
    sa.Enum(name="legal_evidence_status").drop(op.get_bind(), checkfirst=True)
