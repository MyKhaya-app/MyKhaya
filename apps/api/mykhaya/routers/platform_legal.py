"""Platform Control Centre Legal & Compliance routes (Phase 1: backend
core). Access uses the existing platform-admin role model
(require_roles(*OPERATORS)) — no new `legal.manage` permission is
introduced, per the Legal & Compliance brief's decision to follow the
existing PCC role architecture rather than build a parallel one.

Document lifecycle: a LegalDocument has at most one `draft` version and at
most one `published` version at a time. Creating a draft when a published
version already exists is how "editing a published policy" works — the
published row is never mutated. Publishing a draft moves any existing
`published` version to `superseded` and the draft to `published`, all in
one transaction. See mykhaya.legal for the shared status-computation logic
this module's read endpoints build on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.legal import next_version_sequence
from mykhaya.legal_schemas import (
    PlatformLegalArchiveRequest,
    PlatformLegalDocumentCreate,
    PlatformLegalDocumentResponse,
    PlatformLegalDocumentVersionDetail,
    PlatformLegalDocumentVersionSummary,
    PlatformLegalDraftCreate,
    PlatformLegalDraftUpdate,
    PlatformLegalPublishRequest,
)
from mykhaya.legal_test_mode import configuration
from mykhaya.models import (
    LegalAcceptance,
    LegalDocument,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalDocumentScope,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles
from mykhaya.routers.platform import OPERATORS

router = APIRouter(prefix="/platform/legal", tags=["platform-legal"])


async def _load_document(db: AsyncSession, document_id: uuid.UUID) -> LegalDocument:
    document = await db.get(LegalDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That legal document could not be found.")
    return document


async def _load_version(db: AsyncSession, version_id: uuid.UUID) -> LegalDocumentVersion:
    version = await db.get(LegalDocumentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")
    return version


async def _acceptance_count(db: AsyncSession, version_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(LegalAcceptance.id)).where(
                LegalAcceptance.document_version_id == version_id
            )
        )
        or 0
    )


async def _version_summary(
    db: AsyncSession, version: LegalDocumentVersion
) -> PlatformLegalDocumentVersionSummary:
    return PlatformLegalDocumentVersionSummary(
        id=version.id,
        version=version.version,
        version_sequence=version.version_sequence,
        status=version.status,
        effective_date=version.effective_date,
        published_at=version.published_at,
        updated_at=version.updated_at,
        reacceptance_scope=version.reacceptance_scope,
        change_summary=version.change_summary,
        acceptance_count=await _acceptance_count(db, version.id),
        is_test=version.is_test,
    )


async def _document_response(
    db: AsyncSession, document: LegalDocument
) -> PlatformLegalDocumentResponse:
    published = await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document.id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
            LegalDocumentVersion.is_test.is_(False),
        )
    )
    test_published = await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document.id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
            LegalDocumentVersion.is_test.is_(True),
        )
    )
    draft = await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document.id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.draft,
        )
    )
    return PlatformLegalDocumentResponse(
        id=document.id,
        key=document.key,
        display_name=document.display_name,
        audience=document.audience,
        scope=document.scope,
        action_verb=document.action_verb,
        acceptance_required=document.acceptance_required,
        archived_at=document.archived_at,
        published_version=await _version_summary(db, published) if published else None,
        test_published_version=(
            await _version_summary(db, test_published) if test_published else None
        ),
        draft_version=await _version_summary(db, draft) if draft else None,
    )


@router.get("/documents", response_model=list[PlatformLegalDocumentResponse])
async def list_documents(
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformLegalDocumentResponse]:
    documents = (await db.scalars(select(LegalDocument).order_by(LegalDocument.display_name))).all()
    return [await _document_response(db, document) for document in documents]


@router.get("/documents/{document_id}", response_model=PlatformLegalDocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> PlatformLegalDocumentResponse:
    document = await _load_document(db, document_id)
    return await _document_response(db, document)


@router.post(
    "/documents",
    response_model=PlatformLegalDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    body: PlatformLegalDocumentCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> PlatformLegalDocumentResponse:
    existing = await db.scalar(select(LegalDocument).where(LegalDocument.key == body.key))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A legal document with that key already exists."
        )
    document = LegalDocument(
        key=body.key,
        display_name=body.display_name,
        audience=body.audience,
        scope=body.scope,
        action_verb=body.action_verb,
        acceptance_required=body.acceptance_required,
    )
    db.add(document)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_document.created",
        "legal_document",
        document.id,
        new={
            "key": document.key,
            "display_name": document.display_name,
            "audience": document.audience.value,
        },
    )
    await db.commit()
    await db.refresh(document)
    return await _document_response(db, document)


@router.get(
    "/documents/{document_id}/versions", response_model=list[PlatformLegalDocumentVersionDetail]
)
async def list_versions(
    document_id: uuid.UUID,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformLegalDocumentVersionDetail]:
    await _load_document(db, document_id)
    versions = (
        await db.scalars(
            select(LegalDocumentVersion)
            .where(LegalDocumentVersion.document_id == document_id)
            .order_by(LegalDocumentVersion.version_sequence.desc())
        )
    ).all()
    result = []
    for version in versions:
        summary = await _version_summary(db, version)
        result.append(
            PlatformLegalDocumentVersionDetail(
                **summary.model_dump(),
                content_markdown=version.content_markdown,
                created_by_administrator_id=version.created_by_administrator_id,
                updated_by_administrator_id=version.updated_by_administrator_id,
                published_by_administrator_id=version.published_by_administrator_id,
                superseded_at=version.superseded_at,
                superseded_by_version_id=version.superseded_by_version_id,
            )
        )
    return result


@router.post(
    "/documents/{document_id}/versions",
    response_model=PlatformLegalDocumentVersionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    document_id: uuid.UUID,
    body: PlatformLegalDraftCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> PlatformLegalDocumentVersionDetail:
    """Creates a new draft — whether this document has never been published
    before, or is being edited again after a published version already
    exists. Either way the published version (if any) is left untouched;
    see the module docstring."""
    document = await _load_document(db, document_id)
    existing_draft = await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document_id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.draft,
        )
    )
    if existing_draft is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document already has an open draft. Edit or discard it before starting another.",
        )
    version = LegalDocumentVersion(
        document_id=document.id,
        version_sequence=await next_version_sequence(db, document.id),
        version=body.version,
        status=LegalDocumentVersionStatus.draft,
        content_markdown=body.content_markdown,
        change_summary=body.change_summary,
        effective_date=body.effective_date,
        created_by_administrator_id=context.administrator.id,
        updated_by_administrator_id=context.administrator.id,
    )
    db.add(version)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_document.draft_created",
        "legal_document_version",
        version.id,
        new={"document_id": str(document.id), "version": version.version},
    )
    await db.commit()
    await db.refresh(version)
    summary = await _version_summary(db, version)
    return PlatformLegalDocumentVersionDetail(
        **summary.model_dump(),
        content_markdown=version.content_markdown,
        created_by_administrator_id=version.created_by_administrator_id,
        updated_by_administrator_id=version.updated_by_administrator_id,
        published_by_administrator_id=version.published_by_administrator_id,
        superseded_at=version.superseded_at,
        superseded_by_version_id=version.superseded_by_version_id,
    )


@router.patch(
    "/documents/{document_id}/versions/{version_id}",
    response_model=PlatformLegalDocumentVersionDetail,
)
async def update_draft(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: PlatformLegalDraftUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> PlatformLegalDocumentVersionDetail:
    version = await _load_version(db, version_id)
    if version.document_id != document_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")
    if version.status != LegalDocumentVersionStatus.draft:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a draft version can be edited. Published versions are immutable.",
        )
    previous = {
        "content_markdown_length": len(version.content_markdown),
        "version": version.version,
    }
    if body.content_markdown is not None:
        version.content_markdown = body.content_markdown
    if body.version is not None:
        version.version = body.version
    if body.change_summary is not None:
        version.change_summary = body.change_summary
    if body.effective_date is not None:
        version.effective_date = body.effective_date
    version.updated_by_administrator_id = context.administrator.id
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_document.draft_updated",
        "legal_document_version",
        version.id,
        previous=previous,
        new={"version": version.version},
    )
    await db.commit()
    await db.refresh(version)
    summary = await _version_summary(db, version)
    return PlatformLegalDocumentVersionDetail(
        **summary.model_dump(),
        content_markdown=version.content_markdown,
        created_by_administrator_id=version.created_by_administrator_id,
        updated_by_administrator_id=version.updated_by_administrator_id,
        published_by_administrator_id=version.published_by_administrator_id,
        superseded_at=version.superseded_at,
        superseded_by_version_id=version.superseded_by_version_id,
    )


@router.delete(
    "/documents/{document_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def discard_draft(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
) -> None:
    version = await _load_version(db, version_id)
    if version.document_id != document_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")
    if version.status != LegalDocumentVersionStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft version can be discarded.")
    platform_audit(
        db,
        request,
        context,
        "legal_document.draft_discarded",
        "legal_document_version",
        version.id,
        previous={"version": version.version},
    )
    await db.delete(version)
    await db.commit()


@router.post(
    "/documents/{document_id}/versions/{version_id}/publish",
    response_model=PlatformLegalDocumentVersionDetail,
)
async def publish_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: PlatformLegalPublishRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformLegalDocumentVersionDetail:
    require_recent_auth(context, settings)
    if body.is_test and not (await configuration(db, settings))["enabled"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Legal Test Mode must be enabled before publishing a test version.",
        )
    version = await _load_version(db, version_id)
    if version.document_id != document_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document version could not be found.")
    if version.status != LegalDocumentVersionStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft version can be published.")

    now = datetime.now(UTC)
    currently_published = await db.scalar(
        select(LegalDocumentVersion).where(
            LegalDocumentVersion.document_id == document_id,
            LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
            LegalDocumentVersion.is_test.is_(body.is_test),
        )
    )
    if currently_published is not None:
        currently_published.status = LegalDocumentVersionStatus.superseded
        currently_published.superseded_at = now
        currently_published.superseded_by_version_id = version.id
        platform_audit(
            db,
            request,
            context,
            "legal_document.superseded",
            "legal_document_version",
            currently_published.id,
            new={"superseded_by": str(version.id)},
        )

    version.status = LegalDocumentVersionStatus.published
    version.is_test = body.is_test
    version.published_at = now
    version.published_by_administrator_id = context.administrator.id
    version.reacceptance_scope = body.reacceptance_scope
    if body.effective_date is not None:
        version.effective_date = body.effective_date
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_test_version.published" if body.is_test else "legal_document.published",
        "legal_document_version",
        version.id,
        reason=body.reason,
        new={
            "version": version.version,
            "reacceptance_scope": version.reacceptance_scope.value,
            "effective_date": (
                version.effective_date.isoformat() if version.effective_date else None
            ),
        },
    )
    await db.commit()
    await db.refresh(version)
    summary = await _version_summary(db, version)
    return PlatformLegalDocumentVersionDetail(
        **summary.model_dump(),
        content_markdown=version.content_markdown,
        created_by_administrator_id=version.created_by_administrator_id,
        updated_by_administrator_id=version.updated_by_administrator_id,
        published_by_administrator_id=version.published_by_administrator_id,
        superseded_at=version.superseded_at,
        superseded_by_version_id=version.superseded_by_version_id,
    )


@router.post("/documents/{document_id}/archive", response_model=PlatformLegalDocumentResponse)
async def archive_document(
    document_id: uuid.UUID,
    body: PlatformLegalArchiveRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformLegalDocumentResponse:
    require_recent_auth(context, settings)
    document = await _load_document(db, document_id)
    document.archived_at = datetime.now(UTC)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_document.archived",
        "legal_document",
        document.id,
        reason=body.reason,
    )
    await db.commit()
    await db.refresh(document)
    return await _document_response(db, document)
