"""Seed only synthetic, disposable E2E prerequisites for the candidate stack."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mykhaya.models import (
    BetaInvitation,
    BetaInvitationStatus,
    BetaProgramme,
    BetaProgrammeStatus,
    LegalDocument,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalReacceptanceScope,
    PlatformSetting,
    SignupMode,
)
from mykhaya.founding_beta import FOUNDING_BETA_SLUG, invitation_token_hash


BETA_INVITATIONS = {
    "beta.google@e2e.mykhaya.dev": "e2e-beta-google-invitation-token-0001",
    "beta.apple@e2e.mykhaya.dev": "e2e-beta-apple-invitation-token-0001",
    "beta.email@e2e.mykhaya.dev": "e2e-beta-email-invitation-token-0001",
}


async def seed() -> None:
    engine = create_async_engine(os.environ["MYKHAYA_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        terms = await db.scalar(select(LegalDocument).where(LegalDocument.key == "terms"))
        if terms is None:
            raise RuntimeError("migration did not create the Terms document")
        published = await db.scalar(
            select(LegalDocumentVersion).where(
                LegalDocumentVersion.document_id == terms.id,
                LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
                LegalDocumentVersion.is_test.is_(False),
            )
        )
        if published is None:
            draft = await db.scalar(
                select(LegalDocumentVersion).where(
                    LegalDocumentVersion.document_id == terms.id,
                    LegalDocumentVersion.is_test.is_(False),
                ).order_by(LegalDocumentVersion.version_sequence.desc())
            )
            if draft is None:
                draft = LegalDocumentVersion(
                    document_id=terms.id,
                    version_sequence=1,
                    version="e2e-1.0",
                    content_markdown="# Synthetic E2E Terms",
                )
                db.add(draft)
                await db.flush()
            draft.status = LegalDocumentVersionStatus.published
            draft.reacceptance_scope = LegalReacceptanceScope.all_existing_users
            draft.effective_date = date.today()
            terms.acceptance_required = True

        policy = await db.scalar(
            select(PlatformSetting).where(
                PlatformSetting.key == "consumer_browser_mfa_policy"
            )
        )
        if policy is None:
            db.add(
                PlatformSetting(
                    key="consumer_browser_mfa_policy",
                    value={"policy": "required", "allowed_methods": ["email"]},
                )
            )
        else:
            policy.value = {"policy": "required", "allowed_methods": ["email"]}

        mode = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == "signup_mode"))
        if mode is not None:
            mode.value = {"value": SignupMode.mixed.value}
        invite_only = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "invite_only_mode")
        )
        if invite_only is None:
            db.add(PlatformSetting(key="invite_only_mode", value={"value": False}))
        else:
            invite_only.value = {"value": False}

        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        if programme is None:
            raise RuntimeError("migration did not create the Founding Beta programme")
        programme.status = BetaProgrammeStatus.active
        programme.max_homes = 10
        programme.terms_version = programme.terms_version or "1.1"
        for email, token in BETA_INVITATIONS.items():
            invitation = await db.scalar(
                select(BetaInvitation).where(
                    BetaInvitation.programme_id == programme.id,
                    BetaInvitation.email == email,
                )
            )
            if invitation is None:
                db.add(
                    BetaInvitation(
                        programme_id=programme.id,
                        email=email,
                        token_hash=invitation_token_hash(token),
                        status=BetaInvitationStatus.reserved,
                        expires_at=datetime.now(UTC) + timedelta(days=7),
                    )
                )
            else:
                invitation.token_hash = invitation_token_hash(token)
                invitation.status = BetaInvitationStatus.reserved
                invitation.expires_at = datetime.now(UTC) + timedelta(days=7)
        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
