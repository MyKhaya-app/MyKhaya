"""Creates the very first Platform Owner for a fresh MyKhaya installation, or
recovers a deployment that has genuinely lost every Platform Administrator.

This is installation/disaster-recovery tooling, not the normal way to add
administrators. For ongoing administration, a Platform Owner should use
Control Centre → Administrators → Add Administrator (see
mykhaya.routers.platform's /administrators/invitations endpoints and
docs/architecture/administrative-authentication.md) — a proper invitation the
recipient accepts with their own password, going through the same MFA policy
as everyone else. This script bypasses all of that by design (there is no
existing administrator to invite through), which is exactly why it refuses to
run once any administrator already exists — see the count check below."""

import argparse
import asyncio
import getpass

from sqlalchemy import func, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import PlatformAdministrator, PlatformRole
from mykhaya.security import normalise_email, password_hash


async def bootstrap(email: str, display_name: str, password: str) -> None:
    settings = get_settings()
    if not settings.admin_bootstrap_enabled:
        raise RuntimeError(
            "Set MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true for this deliberate operation."
        )
    if len(password) < 16:
        raise ValueError("The bootstrap password must contain at least 16 characters.")
    async with SessionFactory() as db:
        count = await db.scalar(select(func.count(PlatformAdministrator.id))) or 0
        if count:
            raise RuntimeError(
                "A platform administrator already exists; bootstrap is one-time only."
            )
        db.add(
            PlatformAdministrator(
                email=normalise_email(email),
                display_name=display_name.strip(),
                password_hash=password_hash.hash(password),
                role=PlatformRole.owner,
                mfa_enrolled=False,
            )
        )
        await db.commit()
    print("Platform Owner created with MFA unenrolled. Disable bootstrap immediately.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first MyKhaya Platform Owner")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("New Platform Owner password: ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    asyncio.run(bootstrap(args.email, args.display_name, password))


if __name__ == "__main__":
    main()
