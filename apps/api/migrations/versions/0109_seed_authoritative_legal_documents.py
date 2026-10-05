"""Configure the authoritative global and Founding Beta legal documents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0109_authoritative_legal_documents"
down_revision: str | None = "0108_legal_scopes_contexts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENTS = sa.table(
    "legal_documents",
    sa.column("id", sa.UUID()),
    sa.column("key", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column(
        "audience",
        postgresql.ENUM("adult", "child", name="legal_audience", create_type=False),
    ),
    sa.column(
        "scope",
        postgresql.ENUM("global", "founding_beta", name="legal_document_scope", create_type=False),
    ),
    sa.column(
        "action_verb",
        postgresql.ENUM("accept", "acknowledge", name="legal_action_verb", create_type=False),
    ),
    sa.column("acceptance_required", sa.Boolean()),
)
_VERSIONS = sa.table(
    "legal_document_versions",
    sa.column("id", sa.UUID()),
    sa.column("document_id", sa.UUID()),
    sa.column("version_sequence", sa.Integer()),
    sa.column("version", sa.String()),
    sa.column(
        "status",
        postgresql.ENUM(
            "draft", "scheduled", "published", "superseded",
            name="legal_document_version_status", create_type=False,
        ),
    ),
    sa.column("content_markdown", sa.Text()),
    sa.column("change_summary", sa.String()),
    sa.column(
        "reacceptance_scope",
        postgresql.ENUM(
            "none", "new_users_only", "all_existing_users",
            name="legal_reacceptance_scope", create_type=False,
        ),
    ),
    sa.column("effective_date", sa.Date()),
    sa.column("published_at", sa.DateTime(timezone=True)),
)

_BETA_DOCUMENT_ID = "00000000-0000-0000-0000-000000000106"
_BETA_VERSION_ID = "00000000-0000-0000-0000-000000000206"

_BETA_TERMS = """# Founding Beta Terms

These Founding Beta Terms apply to participation in the MyKhaya Founding Beta
programme. They supplement the MyKhaya Terms & Conditions, which continue to
apply to your account and use of the service.

## Founding Beta access

Founding Beta access is a programme benefit for an approved Home. Complimentary
Ultimate access lasts for the lifetime of that Home while the Home remains
eligible under the programme rules. It does not create a separate account or
Home outside the normal MyKhaya account and Home model.

## Programme conditions

Places, invitations, waitlist decisions and capacity exemptions are controlled
by MyKhaya and recorded through the Platform Control Centre. A place may be
withdrawn where the application was ineligible, the programme has ended, or
the Home is used in breach of the MyKhaya Terms & Conditions.

## Changes and acceptance

We may update these terms by publishing a new version. Where renewed action is
required, MyKhaya will ask the applicable Founding Beta participant to review
and accept the current version before continuing.
"""


def upgrade() -> None:
    bind = op.get_bind()

    # Correct the existing seeded document metadata in place. This preserves
    # every existing version and acceptance row.
    bind.execute(
        sa.update(_DOCUMENTS)
        .where(_DOCUMENTS.c.key == "terms")
        .values(scope="global", acceptance_required=True)
    )
    bind.execute(
        sa.update(_DOCUMENTS)
        .where(_DOCUMENTS.c.key.in_(["privacy", "children_privacy", "cookies"]))
        .values(scope="global", acceptance_required=False)
    )

    existing = bind.execute(
        sa.select(_DOCUMENTS.c.id).where(_DOCUMENTS.c.key == "founding_beta_terms")
    ).first()
    if existing is not None:
        return

    bind.execute(
        sa.insert(_DOCUMENTS).values(
            id=_BETA_DOCUMENT_ID,
            key="founding_beta_terms",
            display_name="Founding Beta Terms",
            audience="adult",
            scope="founding_beta",
            action_verb="accept",
            acceptance_required=True,
        )
    )
    bind.execute(
        sa.insert(_VERSIONS).values(
            id=_BETA_VERSION_ID,
            document_id=_BETA_DOCUMENT_ID,
            version_sequence=1,
            version="1.1",
            status="published",
            content_markdown=_BETA_TERMS,
            change_summary="Initial published Founding Beta Terms.",
            reacceptance_scope="all_existing_users",
            effective_date=sa.func.current_date(),
            published_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.delete(_VERSIONS).where(_VERSIONS.c.id == _BETA_VERSION_ID))
    bind.execute(sa.delete(_DOCUMENTS).where(_DOCUMENTS.c.id == _BETA_DOCUMENT_ID))
