"""PCC Legal & Compliance operational views and records for Phase 4."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.legal import (
    child_document_status,
    current_published_version,
    guardian_document_status,
    user_document_status,
)
from mykhaya.legal_test_mode import SETTING_KEY, configuration
from mykhaya.models import (
    ChildProfile,
    LegalAcceptance,
    LegalDocument,
    LegalDocumentVersion,
    LegalRecordType,
    Membership,
    PlatformSetting,
    PrivacyRequest,
    PrivacyRequestStatus,
    Subprocessor,
    SubprocessorState,
    User,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_schemas import (
    AcceptanceDashboardResponse,
    AcceptanceDocumentSummary,
    AcceptanceHistoryItem,
    AcceptanceHistoryResponse,
    AcceptanceUserRow,
    LegalTestModeResponse,
    LegalTestModeUpdate,
    PrivacyRequestCreate,
    PrivacyRequestResponse,
    PrivacyRequestUpdate,
    SubprocessorMutation,
    SubprocessorResponse,
)
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles
from mykhaya.routers.platform import OPERATORS, SUPPORT

router = APIRouter(prefix="/platform/compliance", tags=["platform-compliance"])


@router.get("/legal-test-mode", response_model=LegalTestModeResponse)
async def legal_test_mode(
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalTestModeResponse:
    state = await configuration(db, settings)
    return LegalTestModeResponse(
        enabled=bool(state["enabled"]),
        test_user_ids=[uuid.UUID(value) for value in state["test_user_ids"]],
    )


@router.put("/legal-test-mode", response_model=LegalTestModeResponse)
async def update_legal_test_mode(
    body: LegalTestModeUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LegalTestModeResponse:
    require_recent_auth(context, settings)
    if settings.environment == "production" and not settings.legal_test_mode_production_allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Legal Test Mode is disabled in production.")
    before = await configuration(db, settings)
    row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == SETTING_KEY))
    value = {"enabled": body.enabled, "test_user_ids": [str(item) for item in body.test_user_ids]}
    if row is None:
        row = PlatformSetting(key=SETTING_KEY, value=value, updated_by=context.administrator.id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = context.administrator.id
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "legal_test_mode.enabled" if body.enabled else "legal_test_mode.disabled",
        "platform_setting",
        row.id,
        reason=body.reason,
        previous=before,
        new={"enabled": body.enabled, "test_user_count": len(body.test_user_ids)},
    )
    await db.commit()
    return LegalTestModeResponse(enabled=body.enabled, test_user_ids=body.test_user_ids)


def _history_label(record_type: LegalRecordType) -> str:
    return {
        LegalRecordType.user_acceptance: "Accepted",
        LegalRecordType.user_acknowledgement: "Acknowledged",
        LegalRecordType.guardian_authorisation: "Guardian authorisation recorded",
        LegalRecordType.child_notice_acknowledgement: "Child acknowledgement",
    }[record_type]


async def _legal_documents(
    db: AsyncSession,
    *,
    is_test: bool = False,
) -> tuple[list[LegalDocument], list[LegalDocumentVersion]]:
    documents = list(
        await db.scalars(
            select(LegalDocument)
            .where(LegalDocument.archived_at.is_(None))
            .order_by(LegalDocument.key)
        )
    )
    versions: list[LegalDocumentVersion] = []
    for document in documents:
        current = await current_published_version(db, document, is_test=is_test)
        if current is not None:
            versions.append(current)
    return documents, versions


async def _child_users(db: AsyncSession) -> dict[uuid.UUID, ChildProfile]:
    rows = await db.execute(
        select(Membership.user_id, ChildProfile).join(
            ChildProfile, ChildProfile.membership_id == Membership.id
        )
    )
    return {user_id: profile for user_id, profile in rows}


async def _user_row(
    db: AsyncSession,
    user: User,
    child_profile: ChildProfile | None,
    *,
    is_test: bool = False,
) -> AcceptanceUserRow:
    documents = list(
        await db.scalars(
            select(LegalDocument)
            .where(
                LegalDocument.archived_at.is_(None),
                LegalDocument.audience == ("child" if child_profile else "adult"),
            )
            .order_by(LegalDocument.key)
        )
    )
    document_statuses = []
    for document in documents:
        current = (
            await child_document_status(db, child_profile.id, document, is_test=is_test)
            if child_profile
            else await user_document_status(db, user.id, document, is_test=is_test)
        )
        document_statuses.append(
            {
                "key": document.key,
                "display_name": document.display_name,
                "action_verb": document.action_verb.value if not child_profile else "acknowledge",
                "current_version": current.current_version_label,
                "current_version_id": str(current.current_version_id)
                if current.current_version_id
                else None,
                "required": current.required,
                "satisfied": current.satisfied,
                "last_version": current.last_version_label,
                "last_version_id": str(current.last_version_id)
                if current.last_version_id
                else None,
                "is_test": is_test,
            }
        )
    records = await db.scalars(
        select(LegalAcceptance)
        .where(
            (LegalAcceptance.child_profile_id == child_profile.id)
            if child_profile
            else (LegalAcceptance.user_id == user.id)
        )
        .where(LegalAcceptance.is_test.is_(is_test))
        .order_by(LegalAcceptance.created_at.desc())
        .limit(1)
    )
    latest = next(iter(records), None)
    required = [item for item in document_statuses if item["required"]]
    if not required:
        row_status = "no_applicable_documents"
    elif all(item["satisfied"] for item in required):
        row_status = "up_to_date"
    else:
        row_status = "action_required"
    return AcceptanceUserRow(
        user_id=user.id,
        display_name=user.display_name,
        email="Managed child" if child_profile else user.email,
        account_type="managed_child" if child_profile else "adult",
        documents=document_statuses,
        last_action_at=latest.created_at if latest else None,
        last_action=latest.record_type.value if latest else None,
        status=row_status,
    )


@router.get("/acceptance", response_model=AcceptanceDashboardResponse)
async def acceptance_dashboard(
    scope: Literal["production", "test", "all"] = "production",
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> AcceptanceDashboardResponse:
    users = list(
        await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name))
    )
    child_users = await _child_users(db)
    scopes = [False, True] if scope == "all" else [scope == "test"]
    rows: list[AcceptanceUserRow] = []
    documents: list[AcceptanceDocumentSummary] = []
    pending_guardian = 0
    profiles = list(await db.scalars(select(ChildProfile)))
    for is_test in scopes:
        legal_documents, versions = await _legal_documents(db, is_test=is_test)
        rows.extend(
            [await _user_row(db, user, child_users.get(user.id), is_test=is_test) for user in users]
        )
        documents.extend(
            AcceptanceDocumentSummary(
                key=document.key,
                display_name=document.display_name,
                action_verb=document.action_verb.value,
                current_version=next(
                    (v.version for v in versions if v.document_id == document.id), None
                ),
                current_version_id=next(
                    (v.id for v in versions if v.document_id == document.id), None
                ),
                is_test=is_test,
            )
            for document in legal_documents
        )
        child_docs = [
            doc
            for doc in legal_documents
            if doc.audience.value == "child" and doc.acceptance_required
        ]
        for profile in profiles:
            for doc in child_docs:
                guardian_status = await guardian_document_status(
                    db, profile.id, doc, is_test=is_test
                )
                if not guardian_status.satisfied:
                    pending_guardian += 1
                    break
    return AcceptanceDashboardResponse(
        active_users=len(users),
        up_to_date=sum(row.status == "up_to_date" for row in rows),
        action_required=sum(row.status == "action_required" for row in rows),
        pending_guardian_action=pending_guardian,
        documents=documents,
        rows=rows,
    )


@router.get("/acceptance/{user_id}", response_model=AcceptanceHistoryResponse)
async def acceptance_history(
    user_id: uuid.UUID,
    scope: Literal["production", "test", "all"] = "production",
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> AcceptanceHistoryResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    child_profile = (await _child_users(db)).get(user.id)
    current = await _user_row(db, user, child_profile, is_test=scope == "test")
    query = (
        select(LegalAcceptance, LegalDocumentVersion, LegalDocument)
        .join(LegalDocumentVersion, LegalDocumentVersion.id == LegalAcceptance.document_version_id)
        .join(LegalDocument, LegalDocument.id == LegalDocumentVersion.document_id)
        .where(
            LegalAcceptance.child_profile_id == child_profile.id
            if child_profile
            else LegalAcceptance.user_id == user.id
        )
        .where(
            LegalAcceptance.is_test.is_(scope == "test")
            if scope != "all"
            else LegalAcceptance.is_test.in_((False, True))
        )
        .order_by(LegalAcceptance.created_at.desc())
    )
    history = [
        AcceptanceHistoryItem(
            id=record.id,
            document_key=document.key,
            document_id=document.id,
            display_name=document.display_name,
            version=version.version,
            version_id=version.id,
            record_type=record.record_type.value,
            context=record.context.value,
            platform=record.platform.value,
            created_at=record.created_at,
            guardian_user_id=record.user_id
            if record.record_type == LegalRecordType.guardian_authorisation
            else None,
            child_profile_id=record.child_profile_id,
            is_test=record.is_test,
        )
        for record, version, document in (await db.execute(query)).all()
    ]
    return AcceptanceHistoryResponse(
        user_id=user.id,
        display_name=user.display_name,
        email="Managed child" if child_profile else user.email,
        account_type="managed_child" if child_profile else "adult",
        current_status=current.documents,
        history=history,
    )


def _privacy_response(
    row: PrivacyRequest, user: User | None, now: date | None = None
) -> PrivacyRequestResponse:
    today = now or datetime.now(UTC).date()
    return PrivacyRequestResponse(
        id=row.id,
        reference=row.reference,
        user_id=row.user_id,
        user_display_name=user.display_name if user else None,
        user_email=user.email if user else None,
        request_type=row.request_type,
        received_at=row.received_at,
        identity_status=row.identity_status,
        due_date=row.due_date,
        status=row.status,
        assigned_administrator_id=row.assigned_administrator_id,
        internal_notes=row.internal_notes,
        completed_at=row.completed_at,
        declined_at=row.declined_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        overdue=row.due_date < today
        and row.status not in (PrivacyRequestStatus.completed, PrivacyRequestStatus.declined),
    )


@router.get("/privacy-requests", response_model=list[PrivacyRequestResponse])
async def privacy_requests(
    _: PlatformContext = Depends(require_roles(*SUPPORT)), db: AsyncSession = Depends(get_db)
) -> list[PrivacyRequestResponse]:
    rows = list(
        await db.scalars(
            select(PrivacyRequest).order_by(PrivacyRequest.due_date, PrivacyRequest.created_at)
        )
    )
    users = (
        {
            row.id: row
            for row in (
                await db.scalars(
                    select(User).where(User.id.in_([r.user_id for r in rows if r.user_id]))
                )
            ).all()
        }
        if rows
        else {}
    )
    return [_privacy_response(row, users.get(row.user_id)) for row in rows]


@router.post("/privacy-requests", response_model=PrivacyRequestResponse, status_code=201)
async def create_privacy_request(
    body: PrivacyRequestCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PrivacyRequestResponse:
    require_recent_auth(context, settings)
    user = await db.get(User, body.user_id) if body.user_id else None
    if body.user_id and user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    now = body.received_at or datetime.now(UTC)
    row = PrivacyRequest(
        reference=f"PR-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        user_id=body.user_id,
        request_type=body.request_type,
        received_at=now,
        due_date=body.due_date,
        identity_status=body.identity_status,
        internal_notes=body.internal_notes,
    )
    db.add(row)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "privacy_request.created",
        "privacy_request",
        row.id,
        new={"reference": row.reference, "request_type": row.request_type.value},
    )
    await db.commit()
    await db.refresh(row)
    return _privacy_response(row, user)


@router.patch("/privacy-requests/{request_id}", response_model=PrivacyRequestResponse)
async def update_privacy_request(
    request_id: uuid.UUID,
    body: PrivacyRequestUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PrivacyRequestResponse:
    require_recent_auth(context, settings)
    row = await db.get(PrivacyRequest, request_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That privacy request could not be found.")
    previous = {
        "status": row.status.value,
        "identity_status": row.identity_status.value,
        "due_date": row.due_date.isoformat(),
    }
    if body.status is not None:
        row.status = body.status
        if body.status == PrivacyRequestStatus.completed:
            row.completed_at = datetime.now(UTC)
        if body.status == PrivacyRequestStatus.declined:
            row.declined_at = datetime.now(UTC)
    if body.identity_status is not None:
        row.identity_status = body.identity_status
    if body.due_date is not None:
        row.due_date = body.due_date
    if body.assigned_administrator_id is not None:
        row.assigned_administrator_id = body.assigned_administrator_id
    if body.internal_notes is not None:
        row.internal_notes = body.internal_notes
    platform_audit(
        db,
        request,
        context,
        "privacy_request.updated",
        "privacy_request",
        row.id,
        reason=body.reason,
        previous=previous,
        new={
            "status": row.status.value,
            "identity_status": row.identity_status.value,
            "due_date": row.due_date.isoformat(),
        },
    )
    await db.commit()
    user = await db.get(User, row.user_id) if row.user_id else None
    return _privacy_response(row, user)


@router.get("/retention")
async def retention_overview(
    _: PlatformContext = Depends(require_roles(*SUPPORT)), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    from mykhaya.family_retention import RETENTION_DAYS

    return {
        "entries": [
            {
                "category": "Active accounts",
                "purpose": "Operate user accounts",
                "rule": "Retained while active",
                "status": "enforced",
            },
            {
                "category": "Deleted accounts",
                "purpose": "Lifecycle and compliance evidence",
                "rule": "Archive/anonymise through PCC lifecycle",
                "status": "enforced",
            },
            {
                "category": "Home data",
                "purpose": "Restore after Family expiry",
                "rule": f"{RETENTION_DAYS} days after authoritative Family expiry",
                "status": "enforced",
                "notes": (
                    "HomeRetentionLifecycle and scheduler purge Home-owned data; "
                    "personal calendar data is preserved by the retention service."
                ),
            },
            {
                "category": "Child profiles",
                "purpose": "Managed-child household access",
                "rule": "Follows Home lifecycle",
                "status": "enforced",
            },
            {
                "category": "Calendars, Nudges, Meals, Budget, Driveway",
                "purpose": "Household features",
                "rule": "Follows owning Home lifecycle",
                "status": "enforced",
            },
            {
                "category": "Support screenshots",
                "purpose": "Support investigation",
                "rule": "Attachment storage lifecycle; no independent purge job found",
                "status": "documented_policy_only",
            },
            {
                "category": "Audit logs",
                "purpose": "Security and administrative accountability",
                "rule": "Retained by audit tables; no configurable PCC retention found",
                "status": "documented_policy_only",
            },
            {
                "category": "Application/security logs and Graylog/syslog",
                "purpose": "Operations and incident response",
                "rule": "Local/syslog retention is deployment configured",
                "status": "configuration_dependent",
            },
            {
                "category": "Push tokens",
                "purpose": "Deliver notifications",
                "rule": "Removed when revoked or no longer registered",
                "status": "enforced",
            },
            {
                "category": "Billing records and backups",
                "purpose": "Billing, recovery and legal obligations",
                "rule": "External/provider and deployment retention",
                "status": "configuration_dependent",
            },
        ]
    }


def _subprocessor_response(row: Subprocessor) -> SubprocessorResponse:
    return SubprocessorResponse.model_validate(row, from_attributes=True)


@router.get("/subprocessors", response_model=list[SubprocessorResponse])
async def subprocessors(
    _: PlatformContext = Depends(require_roles(*SUPPORT)), db: AsyncSession = Depends(get_db)
) -> list[SubprocessorResponse]:
    return [
        _subprocessor_response(row)
        for row in (await db.scalars(select(Subprocessor).order_by(Subprocessor.provider))).all()
    ]


@router.post("/subprocessors", response_model=SubprocessorResponse, status_code=201)
async def create_subprocessor(
    body: SubprocessorMutation,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SubprocessorResponse:
    require_recent_auth(context, settings)
    try:
        row = Subprocessor(**body.model_dump(exclude={"reason", "confirmed"}))
        row.state = SubprocessorState(row.state)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That provider state is not supported."
        ) from exc
    db.add(row)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "subprocessor.created",
        "subprocessor",
        row.id,
        reason=body.reason,
        new={"provider": row.provider, "state": row.state.value},
    )
    await db.commit()
    await db.refresh(row)
    return _subprocessor_response(row)


@router.put("/subprocessors/{subprocessor_id}", response_model=SubprocessorResponse)
async def update_subprocessor(
    subprocessor_id: uuid.UUID,
    body: SubprocessorMutation,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SubprocessorResponse:
    require_recent_auth(context, settings)
    row = await db.get(Subprocessor, subprocessor_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That subprocessor could not be found.")
    values = body.model_dump(exclude={"reason", "confirmed"})
    try:
        values["state"] = SubprocessorState(values["state"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That provider state is not supported."
        ) from exc
    for key, value in values.items():
        setattr(row, key, value)
    platform_audit(
        db,
        request,
        context,
        "subprocessor.updated",
        "subprocessor",
        row.id,
        reason=body.reason,
        new={"provider": row.provider, "state": row.state.value},
    )
    await db.commit()
    await db.refresh(row)
    return _subprocessor_response(row)
