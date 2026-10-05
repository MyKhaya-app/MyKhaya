"""Public and authenticated Legal & Compliance routes.

The `/legal/documents*` routes are deliberately unauthenticated (§23 of the
Legal & Compliance brief: public legal pages must work without a session)
and only ever expose a document's *currently published* version — a draft
or scheduled version is never reachable through them. Everything else here
requires a session and records or reads LegalAcceptance rows; see
mykhaya.legal for the shared status logic and mykhaya.models for why a
guardian_authorisation/child_notice_acknowledgement is never conflated with
an adult's own user_acceptance.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.legal import (
    ActionRecordStatus,
    child_document_status,
    child_profile_by_membership_id,
    current_published_version,
    guardian_children,
    guardian_document_status,
    is_guardian_of,
    own_child_profile,
    user_document_status,
)
from mykhaya.legal_schemas import (
    ChildAcknowledgementCreate,
    ChildLegalStatusResponse,
    GuardianAuthorisationCreate,
    LegalAcceptanceCreate,
    LegalDocumentStatusResponse,
    LegalStatusResponse,
    PublicLegalDocumentContent,
    PublicLegalDocumentSummary,
)
from mykhaya.legal_test_mode import is_test_user
from mykhaya.models import (
    BetaEnrollment,
    LegalAcceptance,
    LegalAcceptanceContext,
    LegalActionVerb,
    LegalAudience,
    LegalDocument,
    LegalDocumentScope,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalRecordType,
    SessionKind,
)
from mykhaya.security import resolve_client_ip

router = APIRouter(prefix="/legal", tags=["legal"])


def _status_response(
    record: ActionRecordStatus, *, is_test: bool = False
) -> LegalDocumentStatusResponse:
    return LegalDocumentStatusResponse(
        document_key=record.document_key,
        display_name=record.display_name,
        audience=record.audience,
        action_verb=record.action_verb,
        current_version_id=record.current_version_id,
        current_version_label=record.current_version_label,
        effective_date=record.effective_date,
        required=record.required,
        satisfied=record.satisfied,
        last_version_label=record.last_version_label,
        last_version_id=record.last_version_id,
        last_accepted_at=record.last_accepted_at,
        is_test=is_test,
    )


@router.get("/documents", response_model=list[PublicLegalDocumentSummary])
async def public_documents(db: AsyncSession = Depends(get_db)) -> list[PublicLegalDocumentSummary]:
    documents = (
        await db.scalars(select(LegalDocument).where(LegalDocument.archived_at.is_(None)))
    ).all()
    result = []
    for document in documents:
        current = await current_published_version(db, document)
        if current is None:
            continue
        result.append(
            PublicLegalDocumentSummary(
                key=document.key,
                display_name=document.display_name,
                audience=document.audience,
                scope=document.scope,
                action_verb=document.action_verb,
                acceptance_required=document.acceptance_required,
                current_version=current.version,
                current_version_id=current.id,
                effective_date=current.effective_date,
            )
        )
    return result


@router.get("/documents/{key}", response_model=PublicLegalDocumentContent)
async def public_document_content(
    key: str, db: AsyncSession = Depends(get_db)
) -> PublicLegalDocumentContent:
    document = await db.scalar(
        select(LegalDocument).where(LegalDocument.key == key, LegalDocument.archived_at.is_(None))
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document could not be found.")
    current = await current_published_version(db, document)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document has not been published yet.")
    return PublicLegalDocumentContent(
        key=document.key,
        display_name=document.display_name,
        version=current.version,
        effective_date=current.effective_date,
        published_at=current.published_at,
        change_summary=current.change_summary,
        content_markdown=current.content_markdown,
    )


@router.get("/status", response_model=LegalStatusResponse)
async def legal_status(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalStatusResponse:
    """A managed_child session never sees adult Terms/contract documents —
    only its own guardian-authorisation/child-acknowledgement status, via
    `child_self` — per §18 of the Legal & Compliance brief. An adult session
    sees its own adult-document statuses plus, for each child it guards,
    that child's guardian_authorisation status (never the child's personal
    acknowledgement, which is the child's own action)."""
    test_user = await is_test_user(db, settings, auth.user.id)
    if auth.session.kind == SessionKind.managed_child:
        profile = await own_child_profile(db, auth.user.id)
        child_self: ChildLegalStatusResponse | None = None
        if profile is not None:
            child_documents = (
                await db.scalars(
                    select(LegalDocument).where(
                        LegalDocument.audience == LegalAudience.child,
                        LegalDocument.archived_at.is_(None),
                    )
                )
            ).all()
            # A managed child is expected to have exactly one applicable
            # Family & Children's Privacy Notice; if more than one such
            # document type ever exists, the first outstanding one governs
            # action_required and is what `child_self` reports.
            for child_document in child_documents:
                acknowledgement = await child_document_status(
                    db, profile.id, child_document, is_test=test_user
                )
                if not acknowledgement.satisfied or child_self is None:
                    child_self = ChildLegalStatusResponse(
                        child_membership_id=profile.membership_id,
                        document_key=child_document.key,
                        display_name=child_document.display_name,
                        guardian_authorisation=None,
                        child_acknowledgement=_status_response(acknowledgement, is_test=test_user),
                    )
                    if not acknowledgement.satisfied:
                        break
        ack = child_self.child_acknowledgement if child_self else None
        action_required = bool(ack and not ack.satisfied)
        return LegalStatusResponse(
            documents=[], children=[], child_self=child_self, action_required=action_required
        )

    adult_documents = (
        await db.scalars(
            select(LegalDocument).where(
                LegalDocument.audience == LegalAudience.adult,
                LegalDocument.archived_at.is_(None),
                or_(
                    LegalDocument.scope == LegalDocumentScope.global_,
                    (
                        (LegalDocument.scope == LegalDocumentScope.founding_beta)
                        & exists(
                            select(BetaEnrollment.id).where(
                                BetaEnrollment.joined_user_id == auth.user.id
                            )
                        )
                    ),
                ),
            )
        )
    ).all()
    documents = [
        _status_response(
            await user_document_status(db, auth.user.id, document, is_test=test_user),
            is_test=test_user,
        )
        for document in adult_documents
    ]

    children: list[ChildLegalStatusResponse] = []
    guarded = await guardian_children(db, auth.user.id)
    if guarded:
        child_documents = (
            await db.scalars(
                select(LegalDocument).where(
                    LegalDocument.audience == LegalAudience.child,
                    LegalDocument.archived_at.is_(None),
                )
            )
        ).all()
        for child_document in child_documents:
            for profile in guarded:
                guardian_status = await guardian_document_status(
                    db, profile.id, child_document, is_test=test_user
                )
                children.append(
                    ChildLegalStatusResponse(
                        child_membership_id=profile.membership_id,
                        document_key=child_document.key,
                        display_name=child_document.display_name,
                        guardian_authorisation=_status_response(guardian_status, is_test=test_user),
                        child_acknowledgement=None,
                    )
                )

    # Deliberately excludes outstanding guardian_authorisation entries: that
    # requirement is enforced at its actual point of consequence (enabling
    # a child's managed sign-in — see routers.children.configure_child_login),
    # not as a full-application block on an adult whose own Terms/Privacy
    # are already satisfied and who may not even have login enabled for
    # that child yet.
    action_required = any(not d.satisfied for d in documents)
    return LegalStatusResponse(
        documents=documents, children=children, action_required=action_required
    )


async def _load_published_version(db: AsyncSession, version_id: uuid.UUID) -> LegalDocumentVersion:
    version = await db.get(LegalDocumentVersion, version_id)
    if version is None or version.status != LegalDocumentVersionStatus.published:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a currently published document version can be accepted."
        )
    return version


async def _require_test_access(
    version: LegalDocumentVersion,
    auth: AuthContext,
    db: AsyncSession,
    settings: Settings,
) -> None:
    if version.is_test and not await is_test_user(db, settings, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")


@router.post(
    "/acceptances",
    response_model=LegalDocumentStatusResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_acceptance(
    body: LegalAcceptanceCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalDocumentStatusResponse:
    require_adult_session(auth)
    document = await db.scalar(select(LegalDocument).where(LegalDocument.key == body.document_key))
    if document is None or document.audience != LegalAudience.adult:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document could not be found.")
    version = await _load_published_version(db, body.document_version_id)
    if version.document_id != document.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That version does not belong to this document."
        )
    await _require_test_access(version, auth, db, settings)

    record_type = (
        LegalRecordType.user_acceptance
        if document.action_verb == LegalActionVerb.accept
        else LegalRecordType.user_acknowledgement
    )
    db.add(
        LegalAcceptance(
            record_type=record_type,
            document_version_id=version.id,
            user_id=auth.user.id,
            is_test=version.is_test,
            context=body.context,
            platform=body.platform,
            app_version=body.app_version,
            ip_address=resolve_client_ip(request, settings),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
    )
    await db.commit()
    return _status_response(
        await user_document_status(db, auth.user.id, document, is_test=version.is_test),
        is_test=version.is_test,
    )


@router.post(
    "/guardian-authorisations",
    response_model=LegalDocumentStatusResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_guardian_authorisation(
    body: GuardianAuthorisationCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalDocumentStatusResponse:
    require_adult_session(auth)
    profile = await child_profile_by_membership_id(db, body.child_membership_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That child profile could not be found.")
    if not await is_guardian_of(db, auth.user.id, profile.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You are not a guardian of that child profile."
        )
    version = await _load_published_version(db, body.document_version_id)
    document = await db.get(LegalDocument, version.document_id)
    if document is None or document.audience != LegalAudience.child:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That version does not belong to a child document."
        )
    await _require_test_access(version, auth, db, settings)

    db.add(
        LegalAcceptance(
            record_type=LegalRecordType.guardian_authorisation,
            document_version_id=version.id,
            user_id=auth.user.id,
            child_profile_id=profile.id,
            is_test=version.is_test,
            context=body.context,
            platform=body.platform,
            app_version=body.app_version,
            ip_address=resolve_client_ip(request, settings),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
    )
    await db.commit()
    return _status_response(
        await guardian_document_status(db, profile.id, document, is_test=version.is_test),
        is_test=version.is_test,
    )


@router.post(
    "/child-acknowledgements",
    response_model=LegalDocumentStatusResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_child_acknowledgement(
    body: ChildAcknowledgementCreate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalDocumentStatusResponse:
    """Deliberately does not accept ip_address/user_agent — data-minimisation
    for the child's own action, see mykhaya.models.LegalAcceptance."""
    if auth.session.kind != SessionKind.managed_child:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This action is only available to a Child sign-in."
        )
    profile = await own_child_profile(db, auth.user.id)
    if profile is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No child profile is linked to this sign-in."
        )
    version = await _load_published_version(db, body.document_version_id)
    document = await db.get(LegalDocument, version.document_id)
    if document is None or document.audience != LegalAudience.child:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That version does not belong to a child document."
        )
    await _require_test_access(version, auth, db, settings)

    db.add(
        LegalAcceptance(
            record_type=LegalRecordType.child_notice_acknowledgement,
            document_version_id=version.id,
            child_profile_id=profile.id,
            is_test=version.is_test,
            context=LegalAcceptanceContext.child_login_session,
            platform=body.platform,
            app_version=body.app_version,
        )
    )
    await db.commit()
    return _status_response(
        await child_document_status(db, profile.id, document, is_test=version.is_test),
        is_test=version.is_test,
    )


@router.get("/versions/{version_id}", response_model=PublicLegalDocumentContent)
async def historical_version_content(
    version_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicLegalDocumentContent:
    """Lets a signed-in identity read the exact immutable content of a
    version *they personally have a record against* — an adult's own
    acceptance/acknowledgement, a guardian's authorisation for a child they
    guard, or a managed child's own acknowledgement. Never exposes an
    arbitrary historical version to someone with no recorded relationship
    to it, and never leaks whether a version id exists at all to such a
    caller (404, not 403, either way) — see §21 of the Legal & Compliance
    brief."""
    version = await db.get(LegalDocumentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")

    document = await db.get(LegalDocument, version.document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")
    await _require_test_access(version, auth, db, settings)

    # Current published content is already public through /legal/documents.
    # Allowing the exact published version here lets an authenticated legal
    # gate review the immutable version it is about to record, while the
    # historical path below remains relationship-scoped.
    authorised = version.status == LegalDocumentVersionStatus.published and (
        (
            auth.session.kind == SessionKind.managed_child
            and document.audience == LegalAudience.child
        )
        or (
            auth.session.kind != SessionKind.managed_child
            and document.audience == LegalAudience.adult
        )
    )
    if auth.session.kind == SessionKind.managed_child:
        profile = await own_child_profile(db, auth.user.id)
        if profile is not None:
            authorised = authorised or (
                await db.scalar(
                    select(LegalAcceptance.id).where(
                        LegalAcceptance.document_version_id == version_id,
                        LegalAcceptance.child_profile_id == profile.id,
                        LegalAcceptance.record_type == LegalRecordType.child_notice_acknowledgement,
                    )
                )
                is not None
            )
    else:
        authorised = authorised or (
            await db.scalar(
                select(LegalAcceptance.id).where(
                    LegalAcceptance.document_version_id == version_id,
                    LegalAcceptance.user_id == auth.user.id,
                    LegalAcceptance.record_type.in_(
                        (
                            LegalRecordType.user_acceptance,
                            LegalRecordType.user_acknowledgement,
                            LegalRecordType.guardian_authorisation,
                        )
                    ),
                )
            )
            is not None
        )
    if not authorised:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")

    return PublicLegalDocumentContent(
        key=document.key,
        display_name=document.display_name,
        version=version.version,
        effective_date=version.effective_date,
        published_at=version.published_at,
        change_summary=version.change_summary,
        content_markdown=version.content_markdown,
    )
