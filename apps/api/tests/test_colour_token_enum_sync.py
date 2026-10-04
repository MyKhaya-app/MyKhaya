"""The Postgres colour_token enum must contain every ColourToken.

Membership.colour is stored in the colour_token enum, so adding a palette token in
Python without a migration only fails later, at runtime, when a member happens to be
assigned the new colour (`invalid input value for enum colour_token`).
"""

import pytest
from sqlalchemy import text

from mykhaya.colour_palette import ColourToken
from mykhaya.db import SessionFactory


@pytest.mark.asyncio
async def test_database_colour_token_enum_contains_every_palette_token() -> None:
    async with SessionFactory() as db:
        labels = set(
            (
                await db.scalars(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'colour_token'"
                    )
                )
            ).all()
        )
    missing = {token.value for token in ColourToken} - labels
    assert not missing, f"colour_token enum is missing {sorted(missing)} — add a migration"
