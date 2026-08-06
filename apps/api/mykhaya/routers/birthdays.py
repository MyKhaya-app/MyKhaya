from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import ChildProfile, Membership, User
from mykhaya.notifications.birthday_occurrences import next_birthday_date
from mykhaya.schemas import BirthdayEntry, BirthdayListResponse

router = APIRouter(prefix="/homes", tags=["birthdays"])


@router.get("/{home_id}/birthdays", response_model=BirthdayListResponse)
async def list_birthdays(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BirthdayListResponse:
    await require_capability(home_id, Capability.members_view, auth, db)
    today = datetime.now(UTC).date()

    memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.group_id == home_id, Membership.removed_at.is_(None)
            )
        )
    ).all()

    entries: list[BirthdayEntry] = []
    for membership in memberships:
        user = await db.get(User, membership.user_id)
        if user is None:
            continue
        profile = await db.scalar(
            select(ChildProfile).where(ChildProfile.membership_id == membership.id)
        )
        if profile is not None:
            # A child's birthdate lives on ChildProfile, not the linked User row (which
            # has no self-managed profile — see docs/architecture/data-model.md), and
            # only surfaces at all once a guardian has opted in to visibility.
            if not profile.birthday_visible:
                continue
            if profile.birth_month is None or profile.birth_day is None:
                continue
            entries.append(
                BirthdayEntry(
                    owner_type="child",
                    owner_id=profile.id,
                    display_name=user.display_name,
                    month=profile.birth_month,
                    day=profile.birth_day,
                    next_occurrence_date=next_birthday_date(
                        profile.birth_month, profile.birth_day, today
                    ),
                )
            )
        else:
            if user.birth_month is None or user.birth_day is None:
                continue
            entries.append(
                BirthdayEntry(
                    owner_type="user",
                    owner_id=user.id,
                    display_name=user.display_name,
                    month=user.birth_month,
                    day=user.birth_day,
                    next_occurrence_date=next_birthday_date(
                        user.birth_month, user.birth_day, today
                    ),
                )
            )

    entries.sort(key=lambda entry: entry.next_occurrence_date)
    return BirthdayListResponse(items=entries)
