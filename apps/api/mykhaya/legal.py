"""Legal & Compliance domain logic shared by the public/consumer routes
(routers.legal) and the Platform Control Centre routes
(routers.platform_legal) — see docs/architecture/legal-documents.md.

The one rule everything here exists to protect: a LegalDocumentVersion, once
published, is immutable, and a LegalAcceptance always points at the exact
version it was recorded against. Nothing in this module ever derives
historical compliance from the *current* published version — only from the
version a given acceptance/authorisation/acknowledgement row actually
references.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    ChildProfile,
    GuardianAssignment,
    LegalAcceptance,
    LegalActionVerb,
    LegalAudience,
    LegalDocument,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalReacceptanceScope,
    LegalRecordType,
    Membership,
)

log = structlog.get_logger("legal")


async def current_published_version(
    db: AsyncSession, document: LegalDocument, *, is_test: bool = False
) -> LegalDocumentVersion | None:
    """The single version currently in force for a document — at most one
    version of a document is ever `published` at a time (publishing a new
    one supersedes whichever version held that status), so this is a plain
    equality lookup, not a "latest by date" guess."""
    return await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document.id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
            LegalDocumentVersion.is_test.is_(is_test),
        )
    )


async def next_version_sequence(db: AsyncSession, document_id: uuid.UUID) -> int:
    current_max = await db.scalar(
        select(func.max(LegalDocumentVersion.version_sequence)).where(
            LegalDocumentVersion.document_id == document_id
        )
    )
    return (current_max or 0) + 1


@dataclass(frozen=True)
class ActionRecordStatus:
    """Whether a particular actor (a User for an adult document, or a
    ChildProfile for a child document's guardian/child side) is compliant
    with a document's current published version, and why."""

    document_key: str
    display_name: str
    audience: LegalAudience
    action_verb: LegalActionVerb | None  # None for the child's own acknowledgement side
    current_version_id: uuid.UUID | None
    current_version_label: str | None
    effective_date: object | None
    required: bool
    satisfied: bool
    last_record_id: uuid.UUID | None
    last_version_label: str | None
    last_version_id: uuid.UUID | None
    # The server-recorded moment of the most recent record (whichever
    # version it references — a grandfathered older acceptance included).
    # Always the real, immutable LegalAcceptance.created_at; never fabricated
    # for a document that has no record. Consumers must still gate display
    # on `satisfied` — see the About-page brief: a truthful old timestamp
    # must not be shown as if it satisfied a version that now requires
    # re-acceptance.
    last_accepted_at: datetime | None


def _grandfathered(scope: LegalReacceptanceScope, has_any_prior_record: bool) -> bool:
    if not has_any_prior_record:
        return False
    return scope in (LegalReacceptanceScope.none, LegalReacceptanceScope.new_users_only)


RecordWithVersion = tuple[LegalAcceptance, LegalDocumentVersion]


async def _records_with_versions(
    db: AsyncSession,
    document_id: uuid.UUID,
    where_clause: ColumnElement[bool],
    *,
    is_test: bool = False,
) -> list[tuple[LegalAcceptance, LegalDocumentVersion]]:
    rows = await db.execute(
        select(LegalAcceptance, LegalDocumentVersion)
        .join(LegalDocumentVersion, LegalDocumentVersion.id == LegalAcceptance.document_version_id)
        .where(
            LegalDocumentVersion.document_id == document_id,
            where_clause,
            LegalDocumentVersion.is_test.is_(is_test),
        )
        .order_by(LegalAcceptance.created_at.desc())
    )
    return [(row.LegalAcceptance, row.LegalDocumentVersion) for row in rows]


async def user_document_status(
    db: AsyncSession, user_id: uuid.UUID, document: LegalDocument, *, is_test: bool = False
) -> ActionRecordStatus:
    """Adult-audience compliance for a single document against one User."""
    assert document.audience == LegalAudience.adult
    record_type = (
        LegalRecordType.user_acceptance
        if document.action_verb == LegalActionVerb.accept
        else LegalRecordType.user_acknowledgement
    )
    current = await current_published_version(db, document, is_test=is_test)
    records = await _records_with_versions(
        db,
        document.id,
        (LegalAcceptance.user_id == user_id)
        & (LegalAcceptance.record_type == record_type)
        & LegalAcceptance.child_profile_id.is_(None),
        is_test=is_test,
    )
    return _status_from_records(document, current, records, action_verb=document.action_verb)


async def guardian_document_status(
    db: AsyncSession, child_profile_id: uuid.UUID, document: LegalDocument, *, is_test: bool = False
) -> ActionRecordStatus:
    """Whether ANY guardian of this child has authorised the current version
    — compliance is tracked per child_profile, not per individual
    guardian."""
    assert document.audience == LegalAudience.child
    current = await current_published_version(db, document, is_test=is_test)
    records = await _records_with_versions(
        db,
        document.id,
        (LegalAcceptance.child_profile_id == child_profile_id)
        & (LegalAcceptance.record_type == LegalRecordType.guardian_authorisation),
        is_test=is_test,
    )
    return _status_from_records(document, current, records, action_verb=None)


async def child_document_status(
    db: AsyncSession, child_profile_id: uuid.UUID, document: LegalDocument, *, is_test: bool = False
) -> ActionRecordStatus:
    assert document.audience == LegalAudience.child
    current = await current_published_version(db, document, is_test=is_test)
    records = await _records_with_versions(
        db,
        document.id,
        (LegalAcceptance.child_profile_id == child_profile_id)
        & (LegalAcceptance.record_type == LegalRecordType.child_notice_acknowledgement),
        is_test=is_test,
    )
    return _status_from_records(document, current, records, action_verb=None)


def _status_from_records(
    document: LegalDocument,
    current: LegalDocumentVersion | None,
    records: list[RecordWithVersion],
    action_verb: LegalActionVerb | None,
) -> ActionRecordStatus:
    verb = action_verb
    last_acceptance, last_version = records[0] if records else (None, None)
    if current is None or not document.acceptance_required:
        return ActionRecordStatus(
            document_key=document.key,
            display_name=document.display_name,
            audience=document.audience,
            action_verb=verb,
            current_version_id=current.id if current else None,
            current_version_label=current.version if current else None,
            effective_date=current.effective_date if current else None,
            required=False,
            satisfied=True,
            last_record_id=last_acceptance.id if last_acceptance else None,
            last_version_label=last_version.version if last_version else None,
            last_version_id=last_version.id if last_version else None,
            last_accepted_at=last_acceptance.created_at if last_acceptance else None,
        )
    satisfied_directly = any(
        acceptance.document_version_id == current.id for acceptance, _ in records
    )
    satisfied = satisfied_directly or _grandfathered(current.reacceptance_scope, bool(records))
    return ActionRecordStatus(
        document_key=document.key,
        display_name=document.display_name,
        audience=document.audience,
        action_verb=verb,
        current_version_id=current.id,
        current_version_label=current.version,
        effective_date=current.effective_date,
        required=True,
        satisfied=satisfied,
        last_record_id=last_acceptance.id if last_acceptance else None,
        last_version_label=last_version.version if last_version else None,
        last_version_id=last_version.id if last_version else None,
        last_accepted_at=last_acceptance.created_at if last_acceptance else None,
    )


async def guardian_children(db: AsyncSession, guardian_user_id: uuid.UUID) -> list[ChildProfile]:
    """Every ChildProfile this User is a recorded guardian of, across any
    Home — used to build a guardian's full legal-status view. Returns full
    rows (not just ids) because callers need `membership_id` — the only
    child identifier the consumer API/frontend otherwise ever exposes; see
    ADR-style note on `child_profile_by_membership_id` below."""
    rows = await db.scalars(
        select(ChildProfile)
        .join(GuardianAssignment, GuardianAssignment.child_profile_id == ChildProfile.id)
        .join(Membership, Membership.id == GuardianAssignment.guardian_membership_id)
        .where(Membership.user_id == guardian_user_id, Membership.removed_at.is_(None))
    )
    return list(rows)


async def child_profile_by_membership_id(
    db: AsyncSession, membership_id: uuid.UUID
) -> ChildProfile | None:
    """Resolves the internal ChildProfile row from `membership_id` — the
    only child identifier the consumer frontend ever sees (see
    routers.children). Consumer-facing legal endpoints accept
    `child_membership_id`, never the ChildProfile primary key directly, so
    this is the one place that translation happens."""
    return await db.scalar(select(ChildProfile).where(ChildProfile.membership_id == membership_id))


async def is_guardian_of(
    db: AsyncSession, guardian_user_id: uuid.UUID, child_profile_id: uuid.UUID
) -> bool:
    row = await db.scalar(
        select(GuardianAssignment.id)
        .join(Membership, Membership.id == GuardianAssignment.guardian_membership_id)
        .where(
            Membership.user_id == guardian_user_id,
            Membership.removed_at.is_(None),
            GuardianAssignment.child_profile_id == child_profile_id,
        )
    )
    return row is not None


async def own_child_profile(db: AsyncSession, user_id: uuid.UUID) -> ChildProfile | None:
    """The ChildProfile whose own managed sign-in User is this user_id — used
    to derive which profile a child_notice_acknowledgement is recorded
    against from the caller's own authenticated (managed_child) session,
    never from a client-supplied id."""
    return await db.scalar(
        select(ChildProfile)
        .join(Membership, Membership.id == ChildProfile.membership_id)
        .where(Membership.user_id == user_id)
    )


async def required_adult_documents(db: AsyncSession) -> list[LegalDocument]:
    """Every non-archived adult-audience document an administrator has
    marked as acceptance_required — the set signup (and the adult legal
    gate) must satisfy. Does not filter on whether a version is actually
    published; see `validate_signup_acceptances`, which treats "required
    but nothing published" as a configuration error, not as "not
    required"."""
    rows = await db.scalars(
        select(LegalDocument).where(
            LegalDocument.audience == LegalAudience.adult,
            LegalDocument.acceptance_required.is_(True),
            LegalDocument.archived_at.is_(None),
        )
    )
    return list(rows)


@dataclass(frozen=True)
class ResolvedSignupAcceptance:
    document: LegalDocument
    version: LegalDocumentVersion


async def validate_signup_acceptances(
    db: AsyncSession, submitted: list[tuple[str, uuid.UUID]]
) -> list[ResolvedSignupAcceptance]:
    """Validates a signup request's claimed document/version acceptances
    against the backend's actual current state, server-side, before an
    account is created — the frontend never gets to assert "the user
    accepted the current version" on its own say-so.

    `submitted` is (document_key, document_version_id) pairs exactly as the
    client displayed and the user actioned. Every currently-required adult
    document must be present with its CURRENT published version id — not
    silently re-resolved to whatever is current now if the two differ,
    since that would record acceptance of a document version the user
    never actually saw (see the Legal & Compliance brief's race-condition
    requirement).

    Raises:
        503 if a document is configured as acceptance_required but has no
            published version at all — a misconfiguration, logged for
            operator visibility, never silently skipped.
        422 if a required document's acceptance is missing from `submitted`.
        409 if a required document's submitted version id doesn't match the
            current published version (the version changed under the user,
            or the client sent something stale/incorrect).
    """
    required = await required_adult_documents(db)
    submitted_by_key = dict(submitted)
    resolved: list[ResolvedSignupAcceptance] = []
    for document in required:
        current = await current_published_version(db, document)
        if current is None:
            await log.awarning(
                "legal_signup_misconfigured",
                document_key=document.key,
                document_id=str(document.id),
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Account creation is temporarily unavailable. Please try again shortly.",
            )
        submitted_version_id = submitted_by_key.get(document.key)
        if submitted_version_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "legal_acceptance_required",
                    "message": "Please review and accept the required documents.",
                    "document_key": document.key,
                },
            )
        if submitted_version_id != current.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "legal_document_changed",
                    "message": "These documents have been updated. Please review them again.",
                    "document_key": document.key,
                },
            )
        resolved.append(ResolvedSignupAcceptance(document=document, version=current))
    return resolved


async def guardian_authorisation_satisfied(db: AsyncSession, child_profile_id: uuid.UUID) -> bool:
    """Whether enabling this child's managed sign-in may proceed: True when
    no child-audience document is currently configured as
    acceptance_required (nothing to gate on — preserves existing behaviour
    exactly when Children's Privacy hasn't been published yet), otherwise
    True only once a guardian has authorised the current published
    version."""
    documents = await db.scalars(
        select(LegalDocument).where(
            LegalDocument.audience == LegalAudience.child,
            LegalDocument.acceptance_required.is_(True),
            LegalDocument.archived_at.is_(None),
        )
    )
    for document in documents:
        status_result = await guardian_document_status(db, child_profile_id, document)
        if not status_result.satisfied:
            return False
    return True
