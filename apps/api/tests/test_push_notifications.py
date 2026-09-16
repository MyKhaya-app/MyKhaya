"""Tests for Web Push (VAPID): Platform Admin key management/test-push, household
subscription CRUD and ownership, the Notification Engine's push dispatch (idempotency,
quiet hours, critical bypass), and the worker's push delivery handler (success, expired
subscription pruning, transient-failure retry).

No fake push service exists, so pywebpush.webpush is monkeypatched throughout — mirrors
how test_smtp_settings.py stands in for smtplib.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from pywebpush import WebPushException
from redis.asyncio import Redis
from sqlalchemy import delete, select

from mykhaya import worker as worker_module
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    NativePushDevice,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OutboxEvent,
    PlatformAdministrator,
    PlatformPushSettings,
    PlatformRole,
    PushSubscription,
    TokenPurpose,
    User,
    WorkerJobRecord,
)
from mykhaya.notifications import push as push_module
from mykhaya.notifications.engine import notify
from mykhaya.notifications.push import PushConfig
from mykhaya.routers import platform as platform_router
from mykhaya.secrets_crypto import decrypt_secret
from mykhaya.security import derived_token, password_hash
from mykhaya.worker import process

ADMIN_ORIGIN = "http://admin.localhost:8080"
ORIGIN = "http://localhost:8080"
PASSWORD = "A separate operator password!"
AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def gone_exception() -> WebPushException:
    return WebPushException("gone", response=FakeResponse(410))


def transient_exception() -> WebPushException:
    return WebPushException("unavailable", response=FakeResponse(503))


async def _configured_push_config(settings: object, db: object) -> PushConfig:
    return PushConfig(
        source="platform_admin",
        configured=True,
        public_key="test-public-key",
        private_key="test-private-key",
        subject="mailto:test@example.com",
    )


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.2", 44200)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": "127.0.0.1"},
    ) as value:
        yield value


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    cookie_name = "mk_admin_csrf" if "admin" in str(client.base_url) else "mk_csrf"
    csrf = client.cookies.get(cookie_name)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def create_admin(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"push-operator-{suffix}@example.com",
            display_name="Test Operator",
            password_hash=password_hash.hash(PASSWORD),
            role=role,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": "Correct horse battery staple!"},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client,
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": "Correct horse battery staple!"},
    )
    assert login.status_code == 200
    return user_id


@pytest.fixture(autouse=True)
async def clean_push_settings() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(PlatformPushSettings))
        await db.commit()


async def reset_rate_limit(bucket: str, peer: str) -> None:
    """Clear a rate-limit bucket so reruns within the same window don't flake — the
    limiter (mykhaya.rate_limit.enforce_rate_limit) uses live Redis with no per-test
    isolation."""
    identity = hashlib.sha256(peer.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


def push_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "subject": "mailto:ops@mykhaya.example",
        "reason": "Configuring push for the dev server test suite.",
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


async def generate_keys(admin_client: AsyncClient, rotate: bool = False) -> dict:
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/push/vapid-settings/generate-keys",
        json={"rotate": rotate, "reason": "Generating VAPID keys for tests.", "confirmed": True},
    )
    return response


@pytest.mark.asyncio
async def test_owner_can_generate_keys_and_enable_push(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    generated = await generate_keys(admin_client)
    assert generated.status_code == 200, generated.text
    public_key = generated.json()["public_key"]
    assert public_key

    enabled = await unsafe(
        admin_client, "PUT", "/api/v1/platform/push/vapid-settings", json=push_payload()
    )
    assert enabled.status_code == 200

    read = await admin_client.get("/api/v1/platform/push")
    assert read.status_code == 200
    body = read.json()
    assert body["configured"] is True
    assert body["public_key"] == public_key
    assert "private" not in read.text.lower().replace("private_key_configured", "")


@pytest.mark.asyncio
async def test_generate_keys_requires_rotate_confirmation_once_keys_exist(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    first = await generate_keys(admin_client)
    assert first.status_code == 200
    second = await generate_keys(admin_client, rotate=False)
    assert second.status_code == 409
    rotated = await generate_keys(admin_client, rotate=True)
    assert rotated.status_code == 200
    assert rotated.json()["public_key"] != first.json()["public_key"]


@pytest.mark.asyncio
async def test_private_key_is_encrypted_at_rest(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    await generate_keys(admin_client)
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformPushSettings).limit(1))
        assert row is not None
        assert row.encrypted_vapid_private_key is not None
        decrypted = decrypt_secret(get_settings(), row.encrypted_vapid_private_key)
        assert decrypted and decrypted != row.vapid_public_key


@pytest.mark.asyncio
async def test_enabling_without_keys_is_rejected(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client, "PUT", "/api/v1/platform/push/vapid-settings", json=push_payload()
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_readonly_role_cannot_write_push_settings(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.readonly)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/push/vapid-settings/generate-keys",
        json={"rotate": False, "reason": "Attempted by readonly.", "confirmed": True},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_household_session_has_no_platform_push_access() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.2", 44201)),
        base_url="http://localhost:8080",
        cookies={"mk_session": "household-session", "mk_admin_session": "invented"},
    ) as household_client:
        response = await household_client.get("/api/v1/platform/push")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_environment_managed_push_rejects_admin_writes(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    configured = get_settings().model_copy(
        update={
            "push_delivery_configured": True,
            "vapid_public_key": "env-public-key",
            "vapid_private_key": SecretStr("env-private-key"),
            "vapid_subject": "mailto:env@mykhaya.example",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        read = await admin_client.get("/api/v1/platform/push")
        assert read.json()["managed_by"] == "environment"
        write = await generate_keys(admin_client)
        assert write.status_code == 409
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_push_summary_active_web_subscription_count_excludes_disabled(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    """`active_subscriptions` (kept for compatibility) and the new explicit
    `active_web_subscriptions` must report the identical value, and a
    disabled subscription must not be counted in either."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    baseline = (await admin_client.get("/api/v1/platform/push")).json()

    user_id = await create_verified_user(client, unique_email("web-count"), "Web Count User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/notifications/push-subscriptions",
        json={
            "endpoint": f"https://push.example/{uuid.uuid4()}",
            "keys": {"p256dh": "abc", "auth": "def"},
        },
    )
    assert created.status_code == 201, created.text
    async with SessionFactory() as db:
        db.add(
            PushSubscription(
                user_id=user_id,
                endpoint=f"https://push.example/{uuid.uuid4()}",
                p256dh_key="abc",
                auth_key="def",
                disabled_at=datetime.now(UTC),
                disabled_reason="Disabled for this test.",
            )
        )
        await db.commit()

    after = (await admin_client.get("/api/v1/platform/push")).json()
    assert after["active_web_subscriptions"] == after["active_subscriptions"]
    assert after["active_web_subscriptions"] - baseline["active_web_subscriptions"] == 1


@pytest.mark.asyncio
async def test_push_summary_native_registration_count_and_distinct_users(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    """Active native registrations and distinct users with native push must
    both exclude disabled rows, and two devices for the same user must count
    once toward `users_with_active_native_push` but twice toward
    `active_native_registrations`."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    baseline = (await admin_client.get("/api/v1/platform/push")).json()

    user_a = await create_verified_user(client, unique_email("native-a"), "Native User A")
    user_b = await create_verified_user(client, unique_email("native-b"), "Native User B")
    async with SessionFactory() as db:
        db.add(
            NativePushDevice(
                user_id=user_a,
                platform="ios",
                token="a" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                apns_environment="production",
            )
        )
        db.add(
            NativePushDevice(
                user_id=user_a,
                platform="android",
                token="b" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
            )
        )
        db.add(
            NativePushDevice(
                user_id=user_b,
                platform="ios",
                token="c" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                apns_environment="production",
                disabled_at=datetime.now(UTC),
                disabled_reason="Disabled for this test.",
            )
        )
        await db.commit()

    after = (await admin_client.get("/api/v1/platform/push")).json()
    assert after["active_native_registrations"] - baseline["active_native_registrations"] == 2
    assert after["users_with_active_native_push"] - baseline["users_with_active_native_push"] == 1


@pytest.mark.asyncio
async def test_push_summary_environment_breakdown_buckets_null_as_legacy(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    baseline_body = (await admin_client.get("/api/v1/platform/push")).json()
    baseline = baseline_body["native_registrations_by_environment"]

    user_id = await create_verified_user(
        client, unique_email("env-breakdown"), "Env Breakdown User"
    )
    async with SessionFactory() as db:
        db.add(
            NativePushDevice(
                user_id=user_id,
                platform="ios",
                token="d" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                apns_environment="production",
            )
        )
        db.add(
            NativePushDevice(
                user_id=user_id,
                platform="ios",
                token="e" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                apns_environment="sandbox",
            )
        )
        db.add(
            NativePushDevice(
                user_id=user_id,
                platform="android",
                token="f" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                apns_environment=None,
            )
        )
        await db.commit()

    after = (await admin_client.get("/api/v1/platform/push")).json()[
        "native_registrations_by_environment"
    ]
    assert after["production"] - baseline["production"] == 1
    assert after["sandbox"] - baseline["sandbox"] == 1
    assert after["legacy"] - baseline["legacy"] == 1


@pytest.mark.asyncio
async def test_recent_failures_identify_web_vs_native_with_device_context(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    """A failed web-push delivery and a failed native (sandbox iOS) delivery
    for two different users must each carry enough context to identify
    themselves as such — and a third, successful delivery must not appear
    here at all, proving one failed device is never presented as a whole
    notification/user failure."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    web_user = await create_verified_user(client, unique_email("fail-web"), "Fail Web User")
    native_user = await create_verified_user(
        client, unique_email("fail-native"), "Fail Native User"
    )
    async with SessionFactory() as db:
        web_subscription = PushSubscription(
            user_id=web_user,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        native_device = NativePushDevice(
            user_id=native_user,
            platform="ios",
            token="g" * 64,
            installation_id=f"installation-{uuid.uuid4()}",
            apns_environment="sandbox",
        )
        db.add_all([web_subscription, native_device])
        await db.flush()
        now = datetime.now(UTC)
        web_failure_key = f"test-web-failure:{uuid.uuid4()}"
        native_failure_key = f"test-native-failure:{uuid.uuid4()}"
        succeeded_key = f"test-native-success:{uuid.uuid4()}"
        db.add_all(
            [
                NotificationDelivery(
                    channel="push",
                    recipient_user_id=web_user,
                    notification_type="event_reminder",
                    idempotency_key=web_failure_key,
                    push_subscription_id=web_subscription.id,
                    status=NotificationDeliveryStatus.failed,
                    attempted_at=now,
                    sanitised_failure_reason="Push service temporarily unavailable.",
                ),
                NotificationDelivery(
                    channel="push",
                    recipient_user_id=native_user,
                    notification_type="event_reminder",
                    idempotency_key=native_failure_key,
                    native_push_device_id=native_device.id,
                    status=NotificationDeliveryStatus.failed,
                    attempted_at=now,
                    sanitised_failure_reason="Native push service temporarily unavailable.",
                ),
                # Same user, same notification_type, a *different* device that
                # succeeded — must never appear in recent_failures.
                NotificationDelivery(
                    channel="push",
                    recipient_user_id=native_user,
                    notification_type="event_reminder",
                    idempotency_key=succeeded_key,
                    native_push_device_id=native_device.id,
                    status=NotificationDeliveryStatus.sent,
                    attempted_at=now,
                ),
            ]
        )
        await db.commit()

    read = await admin_client.get("/api/v1/platform/push")
    assert read.status_code == 200
    failures = {row["id"]: row for row in read.json()["recent_failures"]}
    matching_keys = {web_failure_key, native_failure_key, succeeded_key}
    relevant = {
        row_id: row
        for row_id, row in failures.items()
        if row["recipient_user_id"] in (str(web_user), str(native_user))
    }
    # The succeeded delivery must never surface as a failure row.
    assert all(row["notification_type"] == "event_reminder" for row in relevant.values())
    web_rows = [row for row in relevant.values() if row["recipient_user_id"] == str(web_user)]
    native_rows = [row for row in relevant.values() if row["recipient_user_id"] == str(native_user)]
    assert len(web_rows) == 1
    assert web_rows[0]["channel"] == "web"
    assert web_rows[0]["platform"] is None
    assert web_rows[0]["push_subscription_id"] == str(web_subscription.id)
    assert web_rows[0]["native_push_device_id"] is None
    assert len(native_rows) == 1
    assert native_rows[0]["channel"] == "native"
    assert native_rows[0]["platform"] == "ios"
    assert native_rows[0]["apns_environment"] == "sandbox"
    assert native_rows[0]["native_push_device_id"] == str(native_device.id)
    # Exactly two failure rows for these two users — the succeeded delivery
    # never shows up as a third.
    assert len(relevant) == 2
    assert matching_keys  # sanity: keys were constructed, not unused


@pytest.mark.asyncio
async def test_native_device_list_paginates(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    user_id = await create_verified_user(client, unique_email("page-user"), "Page User")
    async with SessionFactory() as db:
        for index in range(3):
            db.add(
                NativePushDevice(
                    user_id=user_id,
                    platform="ios",
                    token=f"{index}" * 64,
                    installation_id=f"installation-page-{uuid.uuid4()}",
                    device_label=f"Device {index}",
                    apns_environment="production",
                )
            )
        await db.commit()

    first_page = await admin_client.get(
        "/api/v1/platform/push/native-devices?page=1&page_size=2"
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["page"] == 1
    assert first_body["page_size"] == 2
    assert first_body["total"] >= 3

    total_pages = -(-first_body["total"] // 2)
    last_page = await admin_client.get(
        f"/api/v1/platform/push/native-devices?page={total_pages}&page_size=2"
    )
    assert last_page.status_code == 200
    seen_ids = {item["id"] for item in first_body["items"]} | {
        item["id"] for item in last_page.json()["items"]
    }
    assert len(seen_ids) >= 3


@pytest.mark.asyncio
async def test_native_device_list_never_exposes_token(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    user_id = await create_verified_user(client, unique_email("token-safety"), "Token Safety User")
    secret_token = "super-secret-device-token-" + uuid.uuid4().hex
    async with SessionFactory() as db:
        db.add(
            NativePushDevice(
                user_id=user_id,
                platform="ios",
                token=secret_token,
                installation_id=f"installation-{uuid.uuid4()}",
                device_label="Token Safety iPhone",
                apns_environment="production",
            )
        )
        await db.commit()

    response = await admin_client.get("/api/v1/platform/push/native-devices?page_size=100")
    assert response.status_code == 200
    assert secret_token not in response.text
    for item in response.json()["items"]:
        assert "token" not in item
    expected_fields = {
        "id",
        "user_id",
        "display_name",
        "email",
        "platform",
        "device_label",
        "installation_id",
        "apns_environment",
        "last_seen_at",
        "disabled_at",
        "disabled_reason",
    }
    matching = next(
        item for item in response.json()["items"] if item["device_label"] == "Token Safety iPhone"
    )
    assert set(matching.keys()) == expected_fields
    assert matching["email"] is not None


@pytest.mark.asyncio
async def test_native_device_list_requires_support_role(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    support = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, support)
    allowed = await admin_client.get("/api/v1/platform/push/native-devices")
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_native_device_list_denied_to_household_session() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.3", 44202)),
        base_url="http://localhost:8080",
        cookies={"mk_session": "household-session", "mk_admin_session": "invented"},
    ) as household_client:
        response = await household_client.get("/api/v1/platform/push/native-devices")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_push_subscription_ownership(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("device"), "Device Owner")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/notifications/push-subscriptions",
        json={
            "endpoint": f"https://push.example/{uuid.uuid4()}",
            "keys": {"p256dh": "abc", "auth": "def"},
            "device_label": "Anthony's iPhone",
        },
    )
    assert created.status_code == 201, created.text
    subscription_id = created.json()["id"]

    listed = await client.get("/api/v1/notifications/push-subscriptions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["device_label"] == "Anthony's iPhone"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as intruder_client:
        await create_verified_user(intruder_client, unique_email("intruder"), "Intruder")
        denied = await unsafe(
            intruder_client,
            "DELETE",
            f"/api/v1/notifications/push-subscriptions/{subscription_id}",
        )
        assert denied.status_code == 404

    removed = await unsafe(
        client, "DELETE", f"/api/v1/notifications/push-subscriptions/{subscription_id}"
    )
    assert removed.status_code == 204
    assert user_id  # sanity: fixture returned a real user id


@pytest.mark.asyncio
async def test_notify_enqueues_push_for_active_subscriptions_and_is_idempotent() -> None:
    async with SessionFactory() as db:
        user = User(email=unique_email("pushnotify"), display_name="Push Notify")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
        subscription = PushSubscription(
            user_id=user_id,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        db.add(subscription)
        await db.commit()

    key = f"pushtest:{uuid.uuid4()}"
    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Push me",
            body="Body",
            idempotency_key=key,
        )
        await db.commit()

    async with SessionFactory() as db:
        deliveries = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key.like(f"{key}:push:%")
                )
            )
        ).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == NotificationDeliveryStatus.queued
        event = await db.get(OutboxEvent, deliveries[0].outbox_event_id)
        assert event is not None
        assert event.topic == "notification.push"

    # A second call with the same idempotency key must not enqueue a duplicate.
    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Push me again",
            body="Body",
            idempotency_key=key,
        )
        await db.commit()
    async with SessionFactory() as db:
        count = len(
            (
                await db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.idempotency_key.like(f"{key}:push:%")
                    )
                )
            ).all()
        )
        assert count == 1


@pytest.mark.asyncio
async def test_quiet_hours_suppresses_push_unless_critical() -> None:
    async with SessionFactory() as db:
        user = User(email=unique_email("quiet"), display_name="Quiet Hours User")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
        db.add(
            PushSubscription(
                user_id=user_id,
                endpoint=f"https://push.example/{uuid.uuid4()}",
                p256dh_key="abc",
                auth_key="def",
            )
        )
        await db.commit()

    from mykhaya.notifications.engine import get_or_create_preferences

    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        # A window covering the full day (UTC) guarantees "now" always falls inside it,
        # regardless of when the test runs.
        prefs.quiet_hours_start = datetime.min.time()
        prefs.quiet_hours_end = datetime.max.time().replace(microsecond=0)
        prefs.quiet_hours_critical_only = True
        await db.commit()

    non_critical_key = f"quiet-normal:{uuid.uuid4()}"
    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Should be suppressed",
            body="Body",
            idempotency_key=non_critical_key,
            is_critical=False,
        )
        await db.commit()
    async with SessionFactory() as db:
        suppressed = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key.like(f"{non_critical_key}:push:%")
                )
            )
        ).all()
        assert suppressed == []

    critical_key = f"quiet-critical:{uuid.uuid4()}"
    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Medication reminder",
            body="Body",
            idempotency_key=critical_key,
            is_critical=True,
        )
        await db.commit()
    async with SessionFactory() as db:
        delivered = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key.like(f"{critical_key}:push:%")
                )
            )
        ).all()
        assert len(delivered) == 1


@pytest.mark.asyncio
async def test_worker_marks_delivery_sent_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_key = f"worker-ok:{uuid.uuid4()}"
    async with SessionFactory() as db:
        user = User(email=unique_email("worker-ok"), display_name="Worker OK")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        subscription = PushSubscription(
            user_id=user.id,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        db.add(subscription)
        event = OutboxEvent(
            topic="notification.push",
            payload={
                "push_subscription_id": None,
                "title": "T",
                "body": "B",
                "deep_link": None,
                "delivery_idempotency_key": ok_key,
                "notification_type": "test",
                "recipient_user_id": str(user.id),
            },
        )
        db.add(event)
        await db.commit()
        await db.refresh(subscription)
        event.payload = {**event.payload, "push_subscription_id": str(subscription.id)}
        db.add(
            NotificationDelivery(
                channel="push",
                recipient_user_id=user.id,
                notification_type="test",
                idempotency_key=ok_key,
                outbox_event_id=event.id,
                push_subscription_id=subscription.id,
            )
        )
        await db.commit()
        event_id = event.id
        subscription_id = subscription.id

    monkeypatch.setattr(worker_module, "resolve_push_config", _configured_push_config)
    monkeypatch.setattr(push_module, "webpush", lambda **kwargs: None)
    await process(event_id)

    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == ok_key)
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.sent
        subscription = await db.get(PushSubscription, subscription_id)
        assert subscription is not None
        assert subscription.disabled_at is None


@pytest.mark.asyncio
async def test_worker_disables_subscription_on_gone_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone_key = f"worker-gone:{uuid.uuid4()}"
    async with SessionFactory() as db:
        user = User(email=unique_email("worker-gone"), display_name="Worker Gone")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        subscription = PushSubscription(
            user_id=user.id,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        event = OutboxEvent(
            topic="notification.push",
            payload={
                "push_subscription_id": str(subscription.id),
                "title": "T",
                "body": "B",
                "deep_link": None,
                "delivery_idempotency_key": gone_key,
                "notification_type": "test",
                "recipient_user_id": str(user.id),
            },
        )
        db.add(event)
        db.add(
            NotificationDelivery(
                channel="push",
                recipient_user_id=user.id,
                notification_type="test",
                idempotency_key=gone_key,
                outbox_event_id=event.id,
                push_subscription_id=subscription.id,
            )
        )
        await db.commit()
        event_id = event.id
        subscription_id = subscription.id

    def fail(**kwargs: object) -> None:
        raise gone_exception()

    monkeypatch.setattr(worker_module, "resolve_push_config", _configured_push_config)
    monkeypatch.setattr(push_module, "webpush", fail)
    # A permanently-gone subscription must not raise — the event completes, it is not
    # retried forever against a dead endpoint.
    await process(event_id)

    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == gone_key)
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.cancelled
        subscription = await db.get(PushSubscription, subscription_id)
        assert subscription is not None
        assert subscription.disabled_at is not None
        event = await db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.processed_at is not None


@pytest.mark.asyncio
async def test_worker_retries_transient_push_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    retry_key = f"worker-retry:{uuid.uuid4()}"
    async with SessionFactory() as db:
        user = User(email=unique_email("worker-retry"), display_name="Worker Retry")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        subscription = PushSubscription(
            user_id=user.id,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        event = OutboxEvent(
            topic="notification.push",
            payload={
                "push_subscription_id": str(subscription.id),
                "title": "T",
                "body": "B",
                "deep_link": None,
                "delivery_idempotency_key": retry_key,
                "notification_type": "test",
                "recipient_user_id": str(user.id),
            },
        )
        db.add(event)
        db.add(
            NotificationDelivery(
                channel="push",
                recipient_user_id=user.id,
                notification_type="test",
                idempotency_key=retry_key,
                outbox_event_id=event.id,
                push_subscription_id=subscription.id,
            )
        )
        await db.commit()
        event_id = event.id
        subscription_id = subscription.id

    def fail(**kwargs: object) -> None:
        raise transient_exception()

    monkeypatch.setattr(worker_module, "resolve_push_config", _configured_push_config)
    monkeypatch.setattr(push_module, "webpush", fail)
    try:
        with pytest.raises(Exception):  # noqa: B017 - re-raised by design, see worker.py
            await process(event_id)

        async with SessionFactory() as db:
            delivery = await db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key == retry_key
                )
            )
            assert delivery is not None
            assert delivery.status == NotificationDeliveryStatus.failed
            subscription = await db.get(PushSubscription, subscription_id)
            assert subscription is not None
            assert subscription.disabled_at is None
            event = await db.get(OutboxEvent, event_id)
            assert event is not None
            # Not marked processed — must remain selectable so the scheduler retries it.
            assert event.processed_at is None
            assert event.available_at > datetime.now(UTC) - timedelta(seconds=1)
    finally:
        # Deliberately left failed + unprocessed (that's the behaviour under test),
        # which also leaves a genuinely "actionable failed job" behind — clean it up
        # so it doesn't pollute anything else in the run that checks the platform
        # overview's actionable-failed-jobs count. See the identical cleanup in
        # test_email_notifications.py::test_worker_delivers_queued_email.
        async with SessionFactory() as db:
            await db.execute(
                delete(WorkerJobRecord).where(WorkerJobRecord.outbox_event_id == event_id)
            )
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            await db.commit()


@pytest.mark.asyncio
async def test_platform_test_push_requires_registered_device(
    admin_client: AsyncClient, admin_factory: AdminFactory, client: AsyncClient
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    await generate_keys(admin_client)
    await unsafe(admin_client, "PUT", "/api/v1/platform/push/vapid-settings", json=push_payload())

    email = unique_email("no-device")
    await create_verified_user(client, email, "No Device")
    await reset_rate_limit("platform-test-push", "127.0.0.2")
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/push/test",
        json={"recipient": email, "reason": "Testing with no device.", "confirmed": True},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_platform_test_push_success_and_failure_are_audited(
    admin_client: AsyncClient,
    admin_factory: AdminFactory,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    await generate_keys(admin_client)
    await unsafe(admin_client, "PUT", "/api/v1/platform/push/vapid-settings", json=push_payload())

    email = unique_email("has-device")
    user_id = await create_verified_user(client, email, "Has Device")
    await unsafe(
        client,
        "POST",
        "/api/v1/notifications/push-subscriptions",
        json={
            "endpoint": f"https://push.example/{uuid.uuid4()}",
            "keys": {"p256dh": "abc", "auth": "def"},
        },
    )

    await reset_rate_limit("platform-test-push", "127.0.0.2")
    monkeypatch.setattr(platform_router, "send_push", lambda *args, **kwargs: None)
    async with SessionFactory() as db:
        db.add(
            NativePushDevice(
                user_id=user_id,
                platform="ios",
                token="b" * 64,
                installation_id=f"installation-{uuid.uuid4()}",
                device_label="Test iPhone",
            )
        )
        await db.commit()
    ok = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/push/test",
        json={"recipient": email, "reason": "Confirming push works.", "confirmed": True},
    )
    assert ok.status_code == 200
    assert {result["channel"] for result in ok.json()["results"]} == {"web", "native"}
    web_result = next(result for result in ok.json()["results"] if result["channel"] == "web")
    assert web_result["result"] == "accepted"
    native_result = next(result for result in ok.json()["results"] if result["channel"] == "native")
    assert native_result["result"] == "queued"
    assert native_result["delivery_id"]
    assert native_result["device_id"]
    assert native_result["environment"] == "production"
    assert not hasattr(platform_router, "send_apns")
    async with SessionFactory() as db:
        native_delivery = await db.get(
            NotificationDelivery, uuid.UUID(native_result["delivery_id"])
        )
        assert native_delivery is not None
        assert native_delivery.native_push_device_id == uuid.UUID(native_result["device_id"])
        native_event = await db.get(OutboxEvent, native_delivery.outbox_event_id)
        assert native_event is not None
        assert native_event.topic == "notification.native_push"

    def fail(*args: object, **kwargs: object) -> None:
        raise gone_exception()

    monkeypatch.setattr(platform_router, "send_push", fail)
    failed = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/push/test",
        json={"recipient": email, "reason": "Confirming failure path.", "confirmed": True},
    )
    assert failed.status_code == 200
    assert failed.json()["results"][0]["result"] == "WebPushException"

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action.in_(["push.test_sent", "push.test_failed"]),
                )
            )
        ).all()
    actions = {event.action for event in events}
    assert actions == {"push.test_sent", "push.test_failed"}
    assert all(email not in str(event.new_values) for event in events)
    assert user_id  # sanity
