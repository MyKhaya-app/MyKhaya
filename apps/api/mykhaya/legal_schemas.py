"""Pydantic schemas for the Legal & Compliance feature, shared by the public/
consumer routes (routers.legal) and the Platform Control Centre routes
(routers.platform_legal)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from mykhaya.models import (
    LegalAcceptanceContext,
    LegalActionVerb,
    LegalAudience,
    LegalDocumentVersionStatus,
    LegalPlatform,
    LegalReacceptanceScope,
)
from mykhaya.schemas import StrictModel

# --- Public/consumer-facing --------------------------------------------------


class PublicLegalDocumentSummary(BaseModel):
    key: str
    display_name: str
    audience: LegalAudience
    action_verb: LegalActionVerb
    acceptance_required: bool
    current_version: str | None
    current_version_id: uuid.UUID | None
    effective_date: date | None


class PublicLegalDocumentContent(BaseModel):
    key: str
    display_name: str
    version: str
    effective_date: date | None
    published_at: datetime | None
    change_summary: str | None
    content_markdown: str


class LegalDocumentStatusResponse(BaseModel):
    document_key: str
    display_name: str
    audience: LegalAudience
    action_verb: LegalActionVerb | None
    current_version_id: uuid.UUID | None
    current_version_label: str | None
    effective_date: date | None
    required: bool
    satisfied: bool
    last_version_label: str | None
    last_version_id: uuid.UUID | None
    last_accepted_at: datetime | None
    is_test: bool = False


class ChildLegalStatusResponse(BaseModel):
    child_membership_id: uuid.UUID
    document_key: str
    display_name: str
    guardian_authorisation: LegalDocumentStatusResponse | None
    child_acknowledgement: LegalDocumentStatusResponse | None


class LegalStatusResponse(BaseModel):
    documents: list[LegalDocumentStatusResponse]
    children: list[ChildLegalStatusResponse]
    # Populated only for a managed_child session — that identity's own
    # guardian-authorisation/child-acknowledgement status, never adult
    # Terms/contract documents (see §18 of the Legal & Compliance brief).
    child_self: ChildLegalStatusResponse | None = None
    action_required: bool


class LegalAcceptanceCreate(StrictModel):
    document_key: str = Field(max_length=50)
    document_version_id: uuid.UUID
    context: LegalAcceptanceContext
    platform: LegalPlatform
    app_version: str | None = Field(default=None, max_length=40)


class GuardianAuthorisationCreate(StrictModel):
    child_membership_id: uuid.UUID
    document_version_id: uuid.UUID
    context: LegalAcceptanceContext
    platform: LegalPlatform
    app_version: str | None = Field(default=None, max_length=40)


class ChildAcknowledgementCreate(StrictModel):
    document_version_id: uuid.UUID
    platform: LegalPlatform
    app_version: str | None = Field(default=None, max_length=40)


# --- Platform Control Centre --------------------------------------------------


class PlatformLegalDocumentCreate(StrictModel):
    key: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=200)
    audience: LegalAudience
    action_verb: LegalActionVerb = LegalActionVerb.accept
    acceptance_required: bool = True


class PlatformLegalDocumentResponse(BaseModel):
    id: uuid.UUID
    key: str
    display_name: str
    audience: LegalAudience
    action_verb: LegalActionVerb
    acceptance_required: bool
    archived_at: datetime | None
    published_version: PlatformLegalDocumentVersionSummary | None = None
    test_published_version: PlatformLegalDocumentVersionSummary | None = None
    draft_version: PlatformLegalDocumentVersionSummary | None = None


class PlatformLegalDocumentVersionSummary(BaseModel):
    id: uuid.UUID
    version: str
    version_sequence: int
    status: LegalDocumentVersionStatus
    effective_date: date | None
    published_at: datetime | None
    updated_at: datetime
    reacceptance_scope: LegalReacceptanceScope
    change_summary: str | None
    acceptance_count: int = 0
    is_test: bool = False


class PlatformLegalDocumentVersionDetail(PlatformLegalDocumentVersionSummary):
    content_markdown: str
    created_by_administrator_id: uuid.UUID | None
    updated_by_administrator_id: uuid.UUID | None
    published_by_administrator_id: uuid.UUID | None
    superseded_at: datetime | None
    superseded_by_version_id: uuid.UUID | None


class PlatformLegalDraftCreate(StrictModel):
    content_markdown: str = Field(min_length=1)
    version: str = Field(min_length=1, max_length=20)
    change_summary: str | None = Field(default=None, max_length=2000)
    effective_date: date | None = None


class PlatformLegalDraftUpdate(StrictModel):
    content_markdown: str | None = Field(default=None, min_length=1)
    version: str | None = Field(default=None, min_length=1, max_length=20)
    change_summary: str | None = Field(default=None, max_length=2000)
    effective_date: date | None = None


class PlatformLegalPublishRequest(StrictModel):
    reacceptance_scope: LegalReacceptanceScope = LegalReacceptanceScope.new_users_only
    effective_date: date | None = None
    reason: str = Field(min_length=10, max_length=500)
    is_test: bool = False


class PlatformLegalArchiveRequest(StrictModel):
    reason: str = Field(min_length=10, max_length=500)


PlatformLegalDocumentResponse.model_rebuild()
