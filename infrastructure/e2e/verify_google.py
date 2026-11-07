"""Authoritative, read-only verification for the disposable Google E2E journey."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


EMAIL = "google.synthetic@e2e.mykhaya.dev"


async def verify() -> None:
    engine = create_async_engine(os.environ["MYKHAYA_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = (await db.execute(text("""
            SELECT id, email FROM users WHERE email = :email
        """), {"email": EMAIL})).mappings().all()
        assert len(user) == 1, f"expected one synthetic User, found {len(user)}"
        user_id = user[0]["id"]

        identities = (await db.execute(text("""
            SELECT provider, provider_subject, user_id
            FROM external_identities
            WHERE user_id = :user_id
        """), {"user_id": user_id})).mappings().all()
        google_identities = [row for row in identities if row["provider"] == "google"]
        assert len(google_identities) == 1, f"expected one Google identity, found {len(google_identities)}"
        assert google_identities[0]["provider_subject"] == "synthetic-google-user"

        required = (await db.execute(text("""
            SELECT d.key, v.id AS version_id, v.version
            FROM legal_documents d
            JOIN legal_document_versions v ON v.document_id = d.id
            WHERE d.acceptance_required = true
              AND d.audience = 'adult'
              AND d.action_verb = 'accept'
              AND d.scope = 'global'
              AND v.status = 'published'
              AND v.is_test = false
        """))).mappings().all()
        acceptances = (await db.execute(text("""
            SELECT d.key, a.document_version_id, v.version, a.created_at, a.context, a.platform
            FROM legal_acceptances a
            JOIN legal_document_versions v ON v.id = a.document_version_id
            JOIN legal_documents d ON d.id = v.document_id
            WHERE a.user_id = :user_id
        """), {"user_id": user_id})).mappings().all()
        required_by_key = {row["key"]: row for row in required}
        accepted_by_key = {row["key"]: row for row in acceptances}
        assert set(accepted_by_key) == set(required_by_key), (
            f"legal evidence mismatch: required={sorted(required_by_key)}, "
            f"accepted={sorted(accepted_by_key)}"
        )
        for key, expected in required_by_key.items():
            actual = accepted_by_key[key]
            assert actual["document_version_id"] == expected["version_id"]
            assert actual["created_at"] is not None
            assert actual["context"] == "signup"
            assert actual["platform"] == "web"

        homes = (await db.execute(text("""
            SELECT g.id, g.name
            FROM groups g
            JOIN group_memberships m ON m.group_id = g.id
            WHERE m.user_id = :user_id AND m.removed_at IS NULL
        """), {"user_id": user_id})).mappings().all()
        assert len(homes) == 1, f"expected one Home, found {len(homes)}"
        home_id = homes[0]["id"]

        subscriptions = (await db.execute(text("""
            SELECT group_id, plan, provider, status, complimentary_source
            FROM home_subscriptions WHERE group_id = :home_id
        """), {"home_id": home_id})).mappings().all()
        assert len(subscriptions) == 1, f"expected one subscription, found {len(subscriptions)}"
        subscription = subscriptions[0]
        assert subscription["plan"] == "free"
        assert subscription["provider"] == "free"
        assert subscription["status"] == "active"
        assert subscription["complimentary_source"] is None

        grants = (await db.execute(text("""
            SELECT COUNT(*) AS count FROM home_entitlement_grants
            WHERE recipient_user_id = :user_id AND revoked_at IS NULL
        """), {"user_id": user_id})).scalar_one()
        assert grants == 0, f"unexpected active entitlement grants: {grants}"

        journeys = (
            ("apple", "apple.synthetic@privaterelay.appleid.com", "apple", "synthetic-apple-user", False),
            ("email", "email.synthetic@e2e.mykhaya.dev", None, None, False),
            ("beta-google", "beta.google@e2e.mykhaya.dev", "google", "synthetic-beta-google-user", True),
            ("beta-apple", "beta.apple@e2e.mykhaya.dev", "apple", "synthetic-beta-apple-user", True),
            ("beta-email", "beta.email@e2e.mykhaya.dev", None, None, True),
        )
        for journey, journey_email, journey_provider, journey_subject, is_beta in journeys:
            rows = (await db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": journey_email})).scalars().all()
            assert len(rows) == 1, f"{journey}: expected one User"
            journey_user = rows[0]
            journey_identities = (await db.execute(text("""
                SELECT provider, provider_subject FROM external_identities WHERE user_id = :user_id
            """), {"user_id": journey_user})).mappings().all()
            if journey_provider is None:
                assert not journey_identities, f"{journey}: unexpected external identity"
            else:
                assert [row for row in journey_identities if row["provider"] == journey_provider] == [
                    {"provider": journey_provider, "provider_subject": journey_subject}
                ]
            journey_acceptances = (await db.execute(text("""
                SELECT a.document_version_id, a.created_at, a.context, a.platform
                FROM legal_acceptances a WHERE a.user_id = :user_id
            """), {"user_id": journey_user})).mappings().all()
            assert len(journey_acceptances) >= len(required_by_key)
            assert all(row["created_at"] is not None and row["platform"] == "web" for row in journey_acceptances)
            journey_homes = (await db.execute(text("""
                SELECT g.id FROM groups g JOIN group_memberships m ON m.group_id = g.id
                WHERE m.user_id = :user_id AND m.removed_at IS NULL
            """), {"user_id": journey_user})).scalars().all()
            assert len(journey_homes) == 1, f"{journey}: expected one Home"
            journey_subscriptions = (await db.execute(text("""
                SELECT plan, provider, status, complimentary_source FROM home_subscriptions WHERE group_id = :home_id
            """), {"home_id": journey_homes[0]})).mappings().all()
            assert len(journey_subscriptions) == 1, f"{journey}: expected one subscription"
            if is_beta:
                assert journey_subscriptions[0]["plan"] == "ultimate"
                assert journey_subscriptions[0]["complimentary_source"] == "founding_beta_lifetime"
                beta_rows = (await db.execute(text("""
                    SELECT id FROM beta_enrollments WHERE joined_user_id = :user_id AND home_id = :home_id
                """), {"user_id": journey_user, "home_id": journey_homes[0]})).scalars().all()
                assert len(beta_rows) == 1, f"{journey}: expected one Beta enrollment"
            else:
                assert journey_subscriptions[0]["plan"] == "free"
                assert journey_subscriptions[0]["provider"] == "free"
                assert journey_subscriptions[0]["complimentary_source"] is None
            print(f"E2E_DB_EVIDENCE journey={journey} user_id={journey_user} home_id={journey_homes[0]}")

        print("GOOGLE_E2E_DB_EVIDENCE")
        print(f"user_id={user_id}")
        print(f"google_identity_count={len(google_identities)}")
        print("legal_acceptances=" + ";".join(
            f"{key}:{accepted_by_key[key]['document_version_id']}:{accepted_by_key[key]['version']}"
            for key in sorted(accepted_by_key)
        ))
        print("legal_contexts=" + ";".join(
            f"{row['key']}:{row['context']}:{row['platform']}:{row['created_at'].isoformat()}"
            for row in sorted(acceptances, key=lambda item: item["key"])
        ))
        print(f"home_id={home_id}")
        print(f"subscription=plan:{subscription['plan']},provider:{subscription['provider']},status:{subscription['status']}")
        print(f"active_entitlement_grants={grants}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify())
