"""Console-only break-glass MFA recovery for a Platform Administrator who has
lost their passkeys, authenticator app, and recovery codes.

Deliberately not exposed through the web UI or any API endpoint — there is no
"Forgot MFA?" flow for platform administrators, since that would be a remote
attack surface against the highest-privilege identity in MyKhaya. This is
local/operator tooling only, run the same way as
mykhaya.bootstrap_platform_owner: `python -m mykhaya.platform_admin_mfa_recovery`.

This clears the target's second factor and revokes their sessions; it never
touches the global admin_mfa_required policy, so a policy that requires MFA
still requires it — the target simply re-enrolls (mfa_setup_required) the next
time they sign in with their password.
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import SessionFactory
from mykhaya.models import (
    AdminRecoveryCode,
    AdminWebAuthnCredential,
    PlatformAdministrator,
    PlatformSession,
    SecurityEvent,
)
from mykhaya.security import normalise_email


async def _find_administrator(db: AsyncSession, email: str) -> PlatformAdministrator | None:
    result: PlatformAdministrator | None = await db.scalar(
        select(PlatformAdministrator).where(PlatformAdministrator.email == normalise_email(email))
    )
    return result


async def reset_mfa(email: str) -> None:
    async with SessionFactory() as db:
        admin = await _find_administrator(db, email)
        if admin is None:
            raise RuntimeError(f"No platform administrator found for {email!r}.")

        webauthn_count = (
            await db.scalar(
                select(AdminWebAuthnCredential.id).where(
                    AdminWebAuthnCredential.administrator_id == admin.id
                )
            )
        ) is not None
        had_totp = admin.totp_enabled
        active_session_count = (
            await db.scalar(
                select(func.count())
                .select_from(PlatformSession)
                .where(
                    PlatformSession.administrator_id == admin.id,
                    PlatformSession.revoked_at.is_(None),
                )
            )
        ) or 0

        admin.totp_enabled = False
        admin.totp_secret_encrypted = None
        admin.totp_verified_at = None
        admin.mfa_enrolled = False
        await db.execute(
            delete(AdminWebAuthnCredential).where(
                AdminWebAuthnCredential.administrator_id == admin.id
            )
        )
        await db.execute(
            delete(AdminRecoveryCode).where(AdminRecoveryCode.administrator_id == admin.id)
        )
        await db.execute(
            update(PlatformSession)
            .where(
                PlatformSession.administrator_id == admin.id,
                PlatformSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        db.add(
            SecurityEvent(
                event_type="administrator_mfa_reset_via_break_glass_cli",
                severity="high",
                outcome="succeeded",
                administrator_id=admin.id,
                safe_detail=(
                    "MFA credentials cleared and sessions revoked via the console-only "
                    "break-glass recovery command."
                ),
            )
        )
        await db.commit()
        print(
            f"Cleared MFA for {admin.email} ({admin.role.value}): "
            f"TOTP={'disabled' if had_totp else 'was not enabled'}, "
            f"WebAuthn credentials={'removed' if webauthn_count else 'none existed'}, "
            f"sessions revoked={active_session_count}."
        )
        print(
            "They will be required to enrol a new MFA method on next sign-in if the "
            "platform MFA policy requires it. The global policy itself is unchanged."
        )


async def _run(email: str, skip_confirmation: bool) -> None:
    async with SessionFactory() as db:
        admin = await _find_administrator(db, email)
    if admin is None:
        raise RuntimeError(f"No platform administrator found for {email!r}.")

    print("About to reset MFA for:")
    print(f"  Email:        {admin.email}")
    print(f"  Display name: {admin.display_name}")
    print(f"  Role:         {admin.role.value}")
    print(f"  Account:      {'active' if admin.is_active else 'DEACTIVATED'}")
    print()
    print("This will:")
    print("  - disable and remove any authenticator app (TOTP) secret")
    print("  - remove every registered passkey")
    print("  - invalidate every recovery code")
    print("  - revoke every active session for this administrator")
    print("The administrator's account, role, and the global MFA policy are unchanged.")
    if not skip_confirmation:
        # A single asyncio.run() drives this whole command, so a synchronous
        # input() here would block the event loop rather than just the
        # terminal; asyncio.to_thread keeps it interactive without that (and
        # without a second asyncio.run() call, which would hand the pooled
        # asyncpg connections above to a loop that no longer exists).
        confirmation = await asyncio.to_thread(
            input, f"\nType the administrator's email ({admin.email}) to confirm: "
        )
        if confirmation.strip() != admin.email:
            raise RuntimeError("Confirmation did not match — aborted, nothing was changed.")
    await reset_mfa(email)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Break-glass: clear a Platform Administrator's MFA (TOTP, passkeys, recovery "
            "codes) and revoke their sessions, for when they've lost access to all of "
            "their second factors. Does not change the global MFA policy or the "
            "administrator's role."
        )
    )
    parser.add_argument("--email", required=True, help="The administrator's email address.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (for scripted/non-interactive use).",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.email, args.yes))


if __name__ == "__main__":
    main()
