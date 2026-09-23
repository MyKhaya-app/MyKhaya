"""Human-readable MK-#### support ticket reference generation.

Backed by a dedicated PostgreSQL sequence (support_ticket_reference_seq,
created in migration 0087_support_tickets) rather than derived from the
ticket's UUID — a sequence gives short, ordered, human-friendly numbers a
support team can read over the phone. Gaps are expected and acceptable (a
rolled-back ticket creation still consumes a sequence value) — this is
explicitly NOT gap-free, matching the Phase 2A decision. The sequence itself
is an internal implementation detail; callers only ever see the formatted
"MK-1001"-style string.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SUPPORT_REFERENCE_SEQUENCE = "support_ticket_reference_seq"


async def next_support_reference(db: AsyncSession) -> str:
    value = await db.scalar(text(f"SELECT nextval('{SUPPORT_REFERENCE_SEQUENCE}')"))
    return f"MK-{value}"
