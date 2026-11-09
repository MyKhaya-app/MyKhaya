from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.legal_evidence_pdf import sha256_text
from mykhaya.models import (
    LegalAcceptance,
    LegalAcceptanceEvidence,
    LegalDocument,
    LegalDocumentVersion,
    OutboxEvent,
    User,
)


def acceptance_timezone(user_timezone: str | None) -> str:
    if user_timezone:
        try:
            ZoneInfo(user_timezone)
            return user_timezone
        except ValueError:
            pass
    return "UTC"


async def queue_acceptance_evidence(
    db: AsyncSession,
    *,
    acceptance: LegalAcceptance,
    document: LegalDocument,
    version: LegalDocumentVersion,
    user: User,
) -> LegalAcceptanceEvidence:
    """Create one immutable evidence snapshot and its transactional outbox row."""
    await db.flush()
    accepted_at = acceptance.created_at or datetime.now(UTC)
    evidence = LegalAcceptanceEvidence(
        acceptance_id=acceptance.id,
        user_id=acceptance.user_id,
        registered_email=user.email,
        account_name=user.display_name,
        document_name=document.display_name,
        document_version=version.version,
        content_markdown=version.content_markdown,
        content_sha256=sha256_text(version.content_markdown),
        accepted_at_utc=accepted_at,
        accepted_timezone=acceptance_timezone(user.timezone),
        ip_address=acceptance.ip_address,
        platform=acceptance.platform,
        action_type=acceptance.record_type,
    )
    db.add(evidence)
    await db.flush()
    db.add(
        OutboxEvent(
            topic="legal.acceptance_evidence",
            dedupe_key=f"legal.acceptance_evidence:{acceptance.id}",
            payload={"evidence_id": str(evidence.id)},
        )
    )
    return evidence
