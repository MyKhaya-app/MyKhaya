"""Existing-account registration and recovery privacy regressions."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import User
from mykhaya.routers.auth import GENERIC_EMAIL_MESSAGE


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        headers={"Origin": "http://localhost:8080"},
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_duplicate_email_registration_does_not_create_or_overwrite_account(
    client: AsyncClient,
) -> None:
    email = f"existing-registration-{uuid4().hex}@example.com"
    first = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Original Name",
            "password": "Correct horse battery staple!",
        },
    )
    assert first.status_code == 202

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email.upper(),
            "display_name": "Replacement Name",
            "password": "Another correct battery staple!",
        },
    )
    assert second.status_code == 202
    assert second.json()["message"] == GENERIC_EMAIL_MESSAGE

    async with SessionFactory() as db:
        users = (await db.scalars(select(User).where(User.email == email))).all()
        assert len(users) == 1
        assert users[0].display_name == "Original Name"


@pytest.mark.asyncio
async def test_forgot_password_response_does_not_disclose_account_existence(
    client: AsyncClient,
) -> None:
    existing_email = f"recovery-existing-{uuid4().hex}@example.com"
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": existing_email,
            "display_name": "Recovery User",
            "password": "Correct horse battery staple!",
        },
    )
    assert created.status_code == 202

    existing = await client.post("/api/v1/auth/forgot-password", json={"email": existing_email})
    unknown = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"unknown-{uuid4().hex}@example.com"},
    )
    assert existing.status_code == unknown.status_code == 202
    assert existing.json() == unknown.json() == {"message": GENERIC_EMAIL_MESSAGE}

    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(User).where(User.email == existing_email)
            )
            == 1
        )
