"""Shared validation for the Home-scoped category used by Nudges."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import TodoCategory


async def category_for_home(
    db: AsyncSession, home_id: uuid.UUID, category_id: uuid.UUID | None
) -> TodoCategory | None:
    """Return a category only when it belongs to the active Home."""
    if category_id is None:
        return None
    category = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.id == category_id,
            TodoCategory.group_id == home_id,
        )
    )
    if category is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That Nudge category is invalid",
        )
    reject_system_category(category)
    return category


def reject_system_category(category: TodoCategory) -> None:
    """A system category (e.g. Driveway) is assigned by its module only —
    never chosen for an ordinary routine, reminder or to-do."""
    if category.managed_source is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That category is kept for vehicle reminders from Driveway.",
        )
