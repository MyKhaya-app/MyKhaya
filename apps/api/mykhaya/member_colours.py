"""Member colours: identity belongs to a person, not an event category.

See docs/design/visual-identity.md. Each membership is assigned one colour
once, at creation, and it never changes silently afterwards (a person can
still choose a different one deliberately via the member colour update
endpoint). Assignment cycles through the shared palette so no two active
members of the same home collide — this is deliberately server-side and
persisted, replacing the earlier client-side colour hash the frontend used
as a placeholder.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.colour_palette import MEMBER_COLOUR_CYCLE, ColourToken
from mykhaya.models import Membership


async def assign_member_colour(db: AsyncSession, group_id: uuid.UUID) -> ColourToken:
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
    for colour in MEMBER_COLOUR_CYCLE:
        if colour not in used:
            return colour
    # More active members than palette colours: cycle deterministically
    # rather than leaving a new member with no colour at all.
    return MEMBER_COLOUR_CYCLE[len(used) % len(MEMBER_COLOUR_CYCLE)]
