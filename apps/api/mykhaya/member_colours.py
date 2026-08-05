"""Member colours: identity belongs to a person, not an event category.

See docs/design/visual-identity.md. Each membership is assigned one colour
once, at creation, and it never changes silently afterwards. Assignment
cycles through the starter palette so no two active members of the same
home collide — this is deliberately server-side and persisted, replacing
the earlier client-side colour hash the frontend used as a placeholder.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import Membership

MEMBER_COLOURS = ["#5C8A54", "#8B6BA8", "#D9A83E", "#4C7FA6"]


async def assign_member_colour(db: AsyncSession, group_id: uuid.UUID) -> str:
    used = set(
        (
            await db.scalars(
                select(Membership.colour).where(
                    Membership.group_id == group_id,
                    Membership.removed_at.is_(None),
                    Membership.colour.is_not(None),
                )
            )
        ).all()
    )
    for colour in MEMBER_COLOURS:
        if colour not in used:
            return colour
    # More active members than starter colours: cycle deterministically
    # rather than leaving a new member with no colour at all.
    return MEMBER_COLOURS[len(used) % len(MEMBER_COLOURS)]
