"""Console-only break-glass MFA recovery — mykhaya.platform_admin_mfa_recovery.
Calls reset_mfa() directly (the async core the CLI's main() wraps with
argparse/confirmation) since that's the actual unit of behaviour; the
interactive confirmation prompt itself is a thin, untestable wrapper around it.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import (
    AdminRecoveryCode,
    AdminWebAuthnCredential,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
    SecurityEvent,
)
from mykhaya.platform_admin_mfa_recovery import reset_mfa
from mykhaya.secrets_crypto import encrypt_secret
from mykhaya.security import hash_secret, password_hash


async def _make_administrator(
    email: str, *, with_mfa: bool = True, role: PlatformRole = PlatformRole.administrator
) -> PlatformAdministrator:
    async with SessionFactory() as db:
        admin = PlatformAdministrator(
            email=email,
            display_name="Recovery Test",
            password_hash=password_hash.hash("A perfectly ordinary password!"),
            role=role,
            mfa_enrolled=with_mfa,
            totp_enabled=with_mfa,
            totp_secret_encrypted=(
                encrypt_secret(get_settings(), "JBSWY3DPEHPK3PXP") if with_mfa else None
            ),
        )
        db.add(admin)
        await db.flush()
        if with_mfa:
            db.add(
                AdminWebAuthnCredential(
                    administrator_id=admin.id,
                    credential_id=f"cred-{admin.id}",
                    public_key="not-a-real-key",
                    label="Test key",
                )
            )
            db.add(
                AdminRecoveryCode(
                    administrator_id=admin.id,
                    code_hash=hash_secret(
                        f"some-code-{admin.id}", get_settings().secret_key.get_secret_value()
                    ),
                )
            )
            db.add(
                PlatformSession(
                    administrator_id=admin.id,
                    token_hash=hash_secret(
                        f"tok-{admin.id}", get_settings().secret_key.get_secret_value()
                    ),
                    idle_expires_at=datetime.now(UTC),
                    absolute_expires_at=datetime.now(UTC),
                    authenticated_at=datetime.now(UTC),
                    last_seen_at=datetime.now(UTC),
                    source_ip="127.0.0.1",
                )
            )
        await db.commit()
        await db.refresh(admin)
        return admin


@pytest.mark.asyncio
async def test_reset_mfa_clears_totp_webauthn_recovery_codes_and_sessions() -> None:
    admin = await _make_administrator("break-glass-full@example.com")
    await reset_mfa(admin.email)

    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.totp_enabled is False
        assert row.totp_secret_encrypted is None
        assert row.mfa_enrolled is False

        webauthn = await db.scalar(
            select(AdminWebAuthnCredential.id).where(
                AdminWebAuthnCredential.administrator_id == admin.id
            )
        )
        assert webauthn is None

        recovery = await db.scalar(
            select(AdminRecoveryCode.id).where(AdminRecoveryCode.administrator_id == admin.id)
        )
        assert recovery is None

        active_sessions = await db.scalar(
            select(PlatformSession.id).where(
                PlatformSession.administrator_id == admin.id,
                PlatformSession.revoked_at.is_(None),
            )
        )
        assert active_sessions is None


@pytest.mark.asyncio
async def test_reset_mfa_preserves_account_role_and_generates_high_severity_audit_event() -> None:
    admin = await _make_administrator("break-glass-audit@example.com", role=PlatformRole.security)
    await reset_mfa(admin.email)

    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.role == PlatformRole.security
        assert row.is_active is True

        event = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.event_type == "administrator_mfa_reset_via_break_glass_cli",
                SecurityEvent.administrator_id == admin.id,
            )
        )
        assert event is not None
        assert event.severity == "high"
        assert event.outcome == "succeeded"


@pytest.mark.asyncio
async def test_reset_mfa_does_not_touch_an_unrelated_administrator() -> None:
    target = await _make_administrator("break-glass-target@example.com")
    other = await _make_administrator("break-glass-bystander@example.com")
    await reset_mfa(target.email)

    async with SessionFactory() as db:
        bystander = await db.get(PlatformAdministrator, other.id)
        assert bystander is not None
        assert bystander.totp_enabled is True
        assert bystander.mfa_enrolled is True
        active_sessions = await db.scalar(
            select(PlatformSession.id).where(
                PlatformSession.administrator_id == other.id,
                PlatformSession.revoked_at.is_(None),
            )
        )
        assert active_sessions is not None


@pytest.mark.asyncio
async def test_reset_mfa_on_administrator_with_no_mfa_configured_is_a_safe_no_op() -> None:
    admin = await _make_administrator("break-glass-no-mfa@example.com", with_mfa=False)
    await reset_mfa(admin.email)
    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.totp_enabled is False
        assert row.mfa_enrolled is False


@pytest.mark.asyncio
async def test_reset_mfa_raises_for_unknown_email() -> None:
    with pytest.raises(RuntimeError):
        await reset_mfa("no-such-administrator-at-all@example.com")
