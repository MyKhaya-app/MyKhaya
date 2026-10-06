"""Regression coverage for the legal-document migration state."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_journey import ORIGIN, PASSWORD, unsafe

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import LegalDocument, LegalDocumentVersion, LegalDocumentVersionStatus


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}"


@pytest.mark.asyncio
async def test_seeded_draft_terms_do_not_block_normal_signup(client: AsyncClient) -> None:
    """The migration must not require the seeded draft Terms document."""
    async with SessionFactory() as db:
        terms = await db.scalar(
            select(LegalDocument).where(
                LegalDocument.key == "terms",
                LegalDocument.archived_at.is_(None),
            )
        )
        assert terms is not None
        assert terms.acceptance_required is False
        versions = list(
            (
                await db.scalars(
                    select(LegalDocumentVersion).where(LegalDocumentVersion.document_id == terms.id)
                )
            ).all()
        )
        assert versions
        assert all(version.status != LegalDocumentVersionStatus.published for version in versions)

    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={
            "email": f"{unique('draft-terms')}@example.com",
            "display_name": "Draft Terms Signup",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 202, response.text
