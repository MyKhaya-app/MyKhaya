"""Slice 4.5 — background-work lifecycle eligibility.

Disabled and Archived (see migration 0053_lifecycle_archived_state) are
both operationally inactive for scheduled work and notifications: neither
should generate new Home-specific work or receive user-targeted
notifications. This module intentionally does not branch on
`archived_at` — `User.is_active`/`Group.is_active` already collapse both
states to `False`, and background work has no reason to tell them apart
(PCC audit/reporting is the only place that distinction matters).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import Group, User


async def is_user_operationally_active(db: AsyncSession, user_id: uuid.UUID) -> bool:
    user = await db.get(User, user_id)
    return user is not None and user.is_active


async def is_home_operationally_active(db: AsyncSession, group_id: uuid.UUID) -> bool:
    group = await db.get(Group, group_id)
    return group is not None and group.is_active
