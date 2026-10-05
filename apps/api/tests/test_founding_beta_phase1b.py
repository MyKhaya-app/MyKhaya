"""Database-backed Phase 1B hardening tests for Founding Beta."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription
from mykhaya.founding_beta import (
    FOUNDING_BETA_SOURCE,
    capacity,
    expire_invitations,
    invitation_token_hash,
    join_beta,
)
from mykhaya.models import (
    BetaEnrollment,
    BetaInvitation,
    BetaInvitationStatus,
    BetaProgramme,
    BetaProgrammeStatus,
    BetaWaitlistEntry,
    BetaWaitlistStatus,
    Group,
    HomeSubscription,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    PlatformSetting,
    Role,
    SignupMode,
    SubscriptionPlan,
    User,
)


async def _programme(db, *, cap: int = 2) -> BetaProgramme:
    programme = BetaProgramme(
        slug=f"test-{uuid.uuid4()}",
        name="Test Beta",
        max_homes=cap,
        terms_version="test-1",
        status=BetaProgrammeStatus.active,
    )
    db.add(programme)
    await db.flush()
    return programme


async def _user(db, *, verified: bool = True, email: str | None = None) -> User:
    user = User(email=email or f"beta-{uuid.uuid4()}@example.com", display_name="Beta Tester")
    if verified:
        user.email_verified_at = datetime.now(UTC)
    db.add(user)
    await db.flush()
    return user


async def _set_mode(mode: SignupMode) -> SignupMode:
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == "signup_mode"))
        assert row is not None
        previous = SignupMode(row.value["value"])
        row.value = {"value": mode.value}
        await db.commit()
        return previous


@pytest.mark.asyncio
async def test_signup_modes_new_user_conversion_paid_and_unverified_paths():
    previous = await _set_mode(SignupMode.beta_only)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db)
            new_user = await _user(db)
            home = await join_beta(
                db,
                user=new_user,
                home_name="New Beta Home",
                terms_version="test-1",
                programme=programme,
            )
            subscription = await db.scalar(
                select(HomeSubscription).where(HomeSubscription.group_id == home.id)
            )
            assert subscription.plan == SubscriptionPlan.ultimate
            assert subscription.complimentary_source == FOUNDING_BETA_SOURCE

            existing = await _user(db)
            existing_home = Group(name="Existing Free", created_by=existing.id)
            db.add(existing_home)
            await db.flush()
            await ensure_home_subscription(db, existing_home.id)
            converted = await join_beta(
                db, user=existing, home_name="ignored", terms_version="test-1", programme=programme
            )
            assert converted.id == existing_home.id

            paid = await _user(db)
            paid_home = Group(name="Paid", created_by=paid.id)
            db.add(paid_home)
            await db.flush()
            paid_subscription = await ensure_home_subscription(db, paid_home.id)
            paid_subscription.plan = SubscriptionPlan.family
            with pytest.raises(HTTPException, match="paid Home"):
                await join_beta(
                    db, user=paid, home_name="no", terms_version="test-1", programme=programme
                )

            unverified = await _user(db, verified=False)
            with pytest.raises(HTTPException, match="Verify your email"):
                await join_beta(
                    db, user=unverified, home_name="no", terms_version="test-1", programme=programme
                )
            await db.rollback()
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
async def test_prior_claim_normalized_email_and_invitation_redemption_are_idempotently_rejected():
    previous = await _set_mode(SignupMode.mixed)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db)
            base = uuid.uuid4()
            user = await _user(db, email=f"Case-{base}@Example.com")
            home = await join_beta(
                db, user=user, home_name="First", terms_version="test-1", programme=programme
            )
            await db.commit()
            with pytest.raises(HTTPException, match="already claimed"):
                await join_beta(
                    db, user=user, home_name="Second", terms_version="test-1", programme=programme
                )
            other = await _user(db, email=f"case-{base}@example.com")
            with pytest.raises(HTTPException, match="already claimed"):
                await join_beta(
                    db,
                    user=other,
                    home_name="Duplicate",
                    terms_version="test-1",
                    programme=programme,
                )
            assert home.id is not None
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
async def test_capacity_waitlist_expiry_and_explicit_exemption_counting():
    async with SessionFactory() as db:
        programme = await _programme(db, cap=3)
        enrolled_user = await _user(db)
        home = Group(name="Managed Demo", created_by=enrolled_user.id)
        db.add(home)
        await db.flush()
        db.add(
            BetaEnrollment(
                programme_id=programme.id,
                home_id=home.id,
                joined_user_id=enrolled_user.id,
                normalized_email=enrolled_user.email,
                joined_by_user_id=enrolled_user.id,
                terms_version="test-1",
                capacity_exempt=False,
            )
        )
        entry = BetaWaitlistEntry(
            programme_id=programme.id,
            name="Waiting",
            email="waiting@example.com",
            normalized_email="waiting@example.com",
            country="GB",
            status=BetaWaitlistStatus.invited,
        )
        db.add(entry)
        await db.flush()
        db.add(
            BetaInvitation(
                programme_id=programme.id,
                waitlist_entry_id=entry.id,
                email=entry.email,
                token_hash=invitation_token_hash("expired-token"),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db.flush()
        state = await capacity(db, programme)
        assert state == {"max_homes": 3, "joined": 1, "reserved": 0, "waiting": 0, "joinable": 2}
        await expire_invitations(db, programme)
        assert (await db.refresh(entry)) is None
        assert entry.status == BetaWaitlistStatus.expired
        invitation = await db.scalar(
            select(BetaInvitation).where(BetaInvitation.programme_id == programme.id)
        )
        assert invitation.status == BetaInvitationStatus.expired
        enrollment = await db.scalar(
            select(BetaEnrollment).where(BetaEnrollment.programme_id == programme.id)
        )
        enrollment.capacity_exempt = True
        assert (await capacity(db, programme))["joined"] == 0
        await db.rollback()


@pytest.mark.asyncio
async def test_waitlist_first_precedence_blocks_non_invited_join():
    previous = await _set_mode(SignupMode.mixed)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db, cap=2)
            db.add(
                BetaWaitlistEntry(
                    programme_id=programme.id,
                    name="Priority",
                    email="priority@example.com",
                    normalized_email="priority@example.com",
                    country="GB",
                )
            )
            user = await _user(db)
            await db.flush()
            with pytest.raises(HTTPException, match="waitlist has priority"):
                await join_beta(
                    db, user=user, home_name="Blocked", terms_version="test-1", programme=programme
                )
            await db.rollback()
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["home_creation", "terms_persistence", "enrollment_creation", "entitlement_grant"]
)
async def test_join_failure_injection_rolls_back_every_created_record(stage: str):
    previous = await _set_mode(SignupMode.beta_only)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db)
            user = await _user(db)

            def fail(current: str) -> None:
                if current == stage:
                    raise RuntimeError(stage)

            with pytest.raises(RuntimeError, match=stage):
                await join_beta(
                    db,
                    user=user,
                    home_name="Atomic",
                    terms_version="test-1",
                    programme=programme,
                    failure_injector=fail,
                )
            await db.rollback()
            assert await db.scalar(select(Group).where(Group.created_by == user.id)) is None
            assert (
                await db.scalar(
                    select(BetaEnrollment).where(BetaEnrollment.joined_user_id == user.id)
                )
                is None
            )
            assert (
                await db.scalar(
                    select(HomeSubscription).where(
                        HomeSubscription.group_id.in_(
                            select(Group.id).where(Group.created_by == user.id)
                        )
                    )
                )
                is None
            )
            assert (await capacity(db, programme))["joined"] == 0
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
async def test_invitation_redemption_failure_does_not_consume_reservation():
    previous = await _set_mode(SignupMode.mixed)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db)
            invite_email = f"invitee-{uuid.uuid4()}@example.com"
            user = await _user(db, email=invite_email)
            entry = BetaWaitlistEntry(
                programme_id=programme.id,
                name="Invitee",
                email=invite_email,
                normalized_email=invite_email,
                country="GB",
                status=BetaWaitlistStatus.invited,
            )
            db.add(entry)
            await db.flush()
            raw_invitation = f"raw-invitation-{uuid.uuid4()}"
            invitation = BetaInvitation(
                programme_id=programme.id,
                waitlist_entry_id=entry.id,
                email=invite_email,
                token_hash=invitation_token_hash(raw_invitation),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            db.add(invitation)
            await db.flush()
            invitation_id = invitation.id
            programme_id = programme.id
            await db.commit()

            def fail(current: str) -> None:
                if current == "invitation_redemption":
                    raise RuntimeError(current)

            with pytest.raises(RuntimeError):
                await join_beta(
                    db,
                    user=user,
                    home_name="Invited",
                    terms_version="test-1",
                    invitation_token=raw_invitation,
                    programme=programme,
                    failure_injector=fail,
                )
            await db.rollback()
            invitation = await db.get(BetaInvitation, invitation_id)
            assert invitation.status == BetaInvitationStatus.reserved
            assert (await capacity(db, await db.get(BetaProgramme, programme_id)))["reserved"] == 1
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
async def test_beta_entitlement_persists_through_mode_closure_owner_and_membership_changes():
    previous = await _set_mode(SignupMode.beta_only)
    try:
        async with SessionFactory() as db:
            programme = await _programme(db)
            owner = await _user(db)
            home = await join_beta(
                db, user=owner, home_name="Persistent", terms_version="test-1", programme=programme
            )
            await db.commit()
            subscription = await db.scalar(
                select(HomeSubscription).where(HomeSubscription.group_id == home.id)
            )
            source = subscription.complimentary_source
            member = await _user(db)
            home.created_by = member.id
            db.add(
                Membership(
                    group_id=home.id,
                    user_id=member.id,
                    role=Role.member,
                    relationship=HouseholdRelationship.review_required,
                    permission_profile=PermissionProfile.review_required,
                )
            )
            programme.status = BetaProgrammeStatus.archived
            await db.commit()
            persisted = await db.scalar(
                select(HomeSubscription).where(HomeSubscription.group_id == home.id)
            )
            assert persisted.complimentary_source == source == FOUNDING_BETA_SOURCE
            assert persisted.plan == SubscriptionPlan.ultimate
    finally:
        await _set_mode(previous)


@pytest.mark.asyncio
async def test_invitation_cancel_and_restore_release_and_reinstate_waitlist_capacity():
    async with SessionFactory() as db:
        programme = await _programme(db, cap=1)
        lifecycle_email = f"life-{uuid.uuid4()}@example.com"
        entry = BetaWaitlistEntry(
            programme_id=programme.id,
            name="Lifecycle",
            email=lifecycle_email,
            normalized_email=lifecycle_email,
            country="GB",
            status=BetaWaitlistStatus.invited,
        )
        db.add(entry)
        await db.flush()
        invitation = BetaInvitation(
            programme_id=programme.id,
            waitlist_entry_id=entry.id,
            email=entry.email,
            token_hash=invitation_token_hash(f"life-{uuid.uuid4()}"),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(invitation)
        await db.flush()
        invitation.status = BetaInvitationStatus.cancelled
        entry.status = BetaWaitlistStatus.waiting
        assert (await capacity(db, programme))["reserved"] == 0
        invitation.status = BetaInvitationStatus.expired
        entry.status = BetaWaitlistStatus.waiting
        assert entry.status == BetaWaitlistStatus.waiting
        await db.rollback()


@pytest.mark.asyncio
async def test_final_place_is_serialized_by_programme_lock():
    previous = await _set_mode(SignupMode.beta_only)
    async with SessionFactory() as setup:
        programme = await _programme(setup, cap=1)
        await setup.commit()
        programme_id = programme.id

    async def attempt() -> bool:
        async with SessionFactory() as db:
            programme_row = await db.get(BetaProgramme, programme_id)
            user = await _user(db)
            try:
                await join_beta(
                    db, user=user, home_name="Race", terms_version="test-1", programme=programme_row
                )
                await db.commit()
                return True
            except HTTPException:
                await db.rollback()
                return False

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == [False, True]
    async with SessionFactory() as db:
        assert (await capacity(db, await db.get(BetaProgramme, programme_id)))["joined"] == 1
    await _set_mode(previous)
