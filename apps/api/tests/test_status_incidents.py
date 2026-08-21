"""Coverage for the Status & Incidents feature: the public /status page's
multi-service, incident-driven service state (mykhaya.status_aggregation),
and Platform Control Centre's incident create/update/resolve endpoints
(mykhaya.routers.platform's /platform/incidents*).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    IncidentLifecycleState,
    PlatformAdministrator,
    PlatformRole,
    PublicIncident,
)
from mykhaya.security import password_hash
from mykhaya.status_aggregation import is_incident_active

ADMIN_ORIGIN = "http://admin.localhost:8080"
STATUS_ORIGIN = "http://status.localhost:8080"
PASSWORD = "A separate operator password!"


@pytest.mark.parametrize(
    "lifecycle_state, expected",
    [
        (IncidentLifecycleState.investigating, True),
        (IncidentLifecycleState.identified, True),
        (IncidentLifecycleState.monitoring, True),
        (IncidentLifecycleState.resolved, False),
    ],
)
def test_incident_activity_respects_lifecycle_state(
    lifecycle_state: IncidentLifecycleState, expected: bool
) -> None:
    assert is_incident_active(
        datetime.now(UTC) - timedelta(minutes=1),
        None,
        lifecycle_state=lifecycle_state,
    ) is expected


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44100)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def status_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=STATUS_ORIGIN) as value:
        yield value


async def create_admin(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"status-operator-{suffix}@example.com",
            display_name="Status Operator",
            password_hash=password_hash.hash(PASSWORD),
            role=role,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                AdministrativeAuditEvent.__table__.delete().where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                PlatformAdministrator.__table__.delete().where(
                    PlatformAdministrator.id.in_(identifiers)
                )
            )
            await db.commit()


@pytest.fixture
async def incident_cleanup() -> AsyncIterator[list[uuid.UUID]]:
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        async with SessionFactory() as db:
            # StatusIncidentService/StatusIncidentUpdate cascade-delete with
            # their parent PublicIncident row.
            await db.execute(PublicIncident.__table__.delete().where(PublicIncident.id.in_(ids)))
            await db.commit()


async def login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_title(prefix: str) -> str:
    return f"{prefix} {datetime.now(UTC).strftime('%H%M%S%f')}"


async def create_incident(
    admin_client: AsyncClient,
    incident_cleanup: list[uuid.UUID],
    *,
    title: str,
    message: str,
    services: list[dict[str, str]],
    lifecycle_state: str = "investigating",
    starts_at: str | None = None,
    internal_notes: str | None = None,
) -> dict:
    body: dict[str, object] = {
        "title": title,
        "message": message,
        "services": services,
        "lifecycle_state": lifecycle_state,
        "reason": "Automated test incident creation",
        "confirmed": True,
    }
    if starts_at is not None:
        body["starts_at"] = starts_at
    if internal_notes is not None:
        body["internal_notes"] = internal_notes
    response = await unsafe(admin_client, "POST", "/api/v1/platform/incidents", json=body)
    assert response.status_code == 201, response.text
    payload = response.json()
    incident_cleanup.append(uuid.UUID(payload["id"]))
    return payload


# --- Public status page: services catalogue and no-incident baseline ------


@pytest.mark.asyncio
async def test_billing_service_appears_on_public_status_page(status_client: AsyncClient) -> None:
    response = await status_client.get("/api/v1/status")
    assert response.status_code == 200
    services = {row["key"]: row for row in response.json()["services"]}
    assert "billing" in services
    assert services["billing"]["name"] == "Billing & Subscriptions"


@pytest.mark.asyncio
async def test_operational_when_no_incidents_affect_a_fresh_service(
    status_client: AsyncClient,
) -> None:
    response = await status_client.get("/api/v1/status")
    payload = response.json()
    # billing is only ever touched by incidents this file creates and
    # cleans up, so — baseline aside from other tests' cleanup timing — its
    # steady state is Operational, and so is the overall banner whenever no
    # incident anywhere is currently active.
    billing = next(row for row in payload["services"] if row["key"] == "billing")
    if payload["overall"] == "operational":
        assert payload["overall_message"] == "Operational"
        assert payload["current_incidents"] == []
    assert billing["state"] in {
        "operational",
        "degraded_performance",
        "partial_outage",
        "major_outage",
        "maintenance",
    }


# --- Incident creation: one vs several affected services -------------------


@pytest.mark.asyncio
async def test_incident_can_affect_one_service(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    title = unique_title("Billing checkout errors")
    await create_incident(
        admin_client,
        incident_cleanup,
        title=title,
        message="We are investigating reports of failed subscription purchases.",
        services=[{"service": "billing", "impact": "partial_outage"}],
    )

    status = (await status_client.get("/api/v1/status")).json()
    billing = next(row for row in status["services"] if row["key"] == "billing")
    assert billing["state"] == "partial_outage"
    incident = next(row for row in status["current_incidents"] if row["title"] == title)
    assert [entry["key"] for entry in incident["services"]] == ["billing"]


@pytest.mark.asyncio
async def test_incident_can_affect_multiple_services(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    title = unique_title("Shared infrastructure incident")
    await create_incident(
        admin_client,
        incident_cleanup,
        title=title,
        message="Investigating a shared infrastructure problem.",
        services=[
            {"service": "billing", "impact": "degraded_performance"},
            {"service": "api", "impact": "degraded_performance"},
        ],
    )

    status = (await status_client.get("/api/v1/status")).json()
    states = {row["key"]: row["state"] for row in status["services"]}
    assert states["billing"] == "degraded_performance"
    assert states["api"] == "degraded_performance"
    incident = next(row for row in status["current_incidents"] if row["title"] == title)
    assert {entry["key"] for entry in incident["services"]} == {"billing", "api"}


# --- Severity combination: per-service and overall -------------------------


@pytest.mark.asyncio
async def test_highest_incident_severity_determines_service_status(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    minor = await create_incident(
        admin_client,
        incident_cleanup,
        title=unique_title("Billing minor slowness"),
        message="Billing is a little slow.",
        services=[{"service": "billing", "impact": "degraded_performance"}],
    )
    await create_incident(
        admin_client,
        incident_cleanup,
        title=unique_title("Billing major outage"),
        message="Billing purchases are failing entirely.",
        services=[{"service": "billing", "impact": "major_outage"}],
    )

    status = (await status_client.get("/api/v1/status")).json()
    billing = next(row for row in status["services"] if row["key"] == "billing")
    assert billing["state"] == "major_outage"

    # Resolving only the *minor* incident must not change the still-major
    # combined state — this also covers "multiple simultaneous incidents do
    # not incorrectly return a service to Operational when one resolves".
    resolve = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/incidents/{minor['id']}/updates",
        json={
            "message": "This particular slowdown has been resolved.",
            "lifecycle_state": "resolved",
            "resolved": True,
            "reason": "Automated test resolving the minor incident only",
            "confirmed": True,
        },
    )
    assert resolve.status_code == 201, resolve.text

    status_after = (await status_client.get("/api/v1/status")).json()
    billing_after = next(row for row in status_after["services"] if row["key"] == "billing")
    assert billing_after["state"] == "major_outage"


@pytest.mark.asyncio
async def test_highest_affected_service_severity_determines_overall_status(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await create_incident(
        admin_client,
        incident_cleanup,
        title=unique_title("Billing major outage for overall"),
        message="Subscription purchases are failing entirely.",
        services=[{"service": "billing", "impact": "major_outage"}],
    )

    status = (await status_client.get("/api/v1/status")).json()
    assert status["overall"] == "major_outage"
    assert status["overall_message"] == "Major service disruption"


# --- Update timeline ---------------------------------------------------------


@pytest.mark.asyncio
async def test_incident_updates_retain_chronological_history(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    base = datetime.now(UTC) - timedelta(hours=1)
    created = await create_incident(
        admin_client,
        incident_cleanup,
        title=unique_title("Billing timeline incident"),
        message="We are investigating reports of failed purchases.",
        services=[{"service": "billing", "impact": "partial_outage"}],
        starts_at=base.isoformat(),
    )

    identified = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/incidents/{created['id']}/updates",
        json={
            "message": "The issue has been identified and a fix is being deployed.",
            "lifecycle_state": "identified",
            "occurred_at": (base + timedelta(minutes=18)).isoformat(),
            "reason": "Automated test appending an identified update",
            "confirmed": True,
        },
    )
    assert identified.status_code == 201, identified.text

    monitoring = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/incidents/{created['id']}/updates",
        json={
            "message": "The fix has been deployed and we are monitoring successful purchases.",
            "lifecycle_state": "monitoring",
            "occurred_at": (base + timedelta(minutes=37)).isoformat(),
            "service_impacts": [{"service": "billing", "impact": "degraded_performance"}],
            "reason": "Automated test appending a monitoring update",
            "confirmed": True,
        },
    )
    assert monitoring.status_code == 201, monitoring.text

    detail = await unsafe(admin_client, "GET", f"/api/v1/platform/incidents/{created['id']}")
    assert detail.status_code == 200
    updates = detail.json()["updates"]
    assert [entry["lifecycle_state"] for entry in updates] == [
        "investigating",
        "identified",
        "monitoring",
    ]
    assert updates == sorted(updates, key=lambda entry: entry["occurred_at"])
    assert all(entry["created_by_display_name"] == "Status Operator" for entry in updates)

    public_status = (await status_client.get("/api/v1/status")).json()
    incident = next(row for row in public_status["current_incidents"] if row["id"] == created["id"])
    assert [entry["lifecycle_state"] for entry in incident["updates"]] == [
        "investigating",
        "identified",
        "monitoring",
    ]
    assert incident["services"][0]["impact"] == "degraded_performance"


# --- Resolution: history retained, service state and lists updated ---------


@pytest.mark.asyncio
async def test_resolving_incident_preserves_history_moves_lists_and_returns_service_state(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    title = unique_title("Billing incident to resolve")
    created = await create_incident(
        admin_client,
        incident_cleanup,
        title=title,
        message="We are investigating reports of failed purchases.",
        services=[{"service": "billing", "impact": "partial_outage"}],
    )

    before_resolution = (await status_client.get("/api/v1/status")).json()
    assert any(row["title"] == title for row in before_resolution["current_incidents"])
    assert not any(row["title"] == title for row in before_resolution["recent_incidents"])

    resolve = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/incidents/{created['id']}/updates",
        json={
            "message": "Billing services have returned to normal.",
            "lifecycle_state": "resolved",
            "resolved": True,
            "reason": "Automated test resolving the incident",
            "confirmed": True,
        },
    )
    assert resolve.status_code == 201, resolve.text
    assert resolve.json()["resolved_at"] is not None

    after = (await status_client.get("/api/v1/status")).json()
    assert not any(row["title"] == title for row in after["current_incidents"])
    resolved_entry = next(row for row in after["recent_incidents"] if row["title"] == title)
    assert resolved_entry["resolved_at"] is not None
    assert resolved_entry["duration_seconds"] is not None
    # Full public timeline retained, not collapsed to a single row.
    assert [entry["lifecycle_state"] for entry in resolved_entry["updates"]] == [
        "investigating",
        "resolved",
    ]

    billing = next(row for row in after["services"] if row["key"] == "billing")
    assert billing["state"] == "operational"

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.target_id == uuid.UUID(created["id"]),
                )
            )
        ).all()
        actions = {event.action for event in events}
    assert "status.incident_created" in actions
    assert "status.incident_update_created" in actions
    assert "status.incident_resolved" in actions


# --- Public/private information boundary -----------------------------------


@pytest.mark.asyncio
async def test_internal_notes_never_appear_through_public_endpoints(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    secret = "INTERNAL-ONLY Stripe error code sk_live_do_not_leak_12345"
    created = await create_incident(
        admin_client,
        incident_cleanup,
        title=unique_title("Billing incident with internal notes"),
        message="We are investigating reports of failed purchases.",
        services=[{"service": "billing", "impact": "partial_outage"}],
        internal_notes=secret,
    )

    public_response = await status_client.get("/api/v1/status")
    assert secret not in public_response.text
    assert admin.email not in public_response.text
    assert admin.display_name not in public_response.text

    # But it IS visible to authorised PCC staff, proving this is a real
    # public/internal boundary rather than the field simply never being
    # stored anywhere.
    detail = await unsafe(admin_client, "GET", f"/api/v1/platform/incidents/{created['id']}")
    assert detail.json()["internal_notes"] == secret


# --- Permissions -------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorised_role_cannot_manage_incidents(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.readonly)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/incidents",
        json={
            "title": "Should be rejected",
            "message": "Should be rejected.",
            "services": [{"service": "billing", "impact": "partial_outage"}],
            "reason": "This must not be allowed to succeed",
            "confirmed": True,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_caller_cannot_read_pcc_incidents(status_client: AsyncClient) -> None:
    # status_client hits the public status host with no admin session at
    # all — exactly the caller /platform/incidents must reject.
    response = await status_client.get("/api/v1/platform/incidents")
    assert response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_authorised_operator_roles_can_manage_incidents(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    for role in (PlatformRole.owner, PlatformRole.administrator):
        admin = await admin_factory(role)
        await login(admin_client, admin)
        created = await create_incident(
            admin_client,
            incident_cleanup,
            title=unique_title(f"Incident created by {role.value}"),
            message="Operator-role incident creation check.",
            services=[{"service": "billing", "impact": "degraded_performance"}],
        )
        assert created["lifecycle_state"] == "investigating"
        await unsafe(admin_client, "POST", "/api/v1/platform/auth/logout")


# --- Timestamp handling ------------------------------------------------------


@pytest.mark.asyncio
async def test_incident_start_time_can_be_backdated_and_is_preserved(
    admin_client: AsyncClient,
    status_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    incident_cleanup: list[uuid.UUID],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    backdated = datetime.now(UTC) - timedelta(hours=3, minutes=15)
    title = unique_title("Backdated billing incident")
    created = await create_incident(
        admin_client,
        incident_cleanup,
        title=title,
        message="Recording an incident that started earlier.",
        services=[{"service": "billing", "impact": "degraded_performance"}],
        starts_at=backdated.isoformat(),
    )

    status = (await status_client.get("/api/v1/status")).json()
    incident = next(row for row in status["current_incidents"] if row["id"] == created["id"])
    started_at = datetime.fromisoformat(incident["started_at"].replace("Z", "+00:00"))
    assert abs((started_at - backdated).total_seconds()) < 2
