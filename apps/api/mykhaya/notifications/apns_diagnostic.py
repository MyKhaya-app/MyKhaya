"""Console-only APNs provider JWT diagnostic.

This command deliberately builds one JWT through the same signer used by
``send_apns`` and sends nothing. The JWT is printed only because an operator
explicitly invoked this module; never redirect its output into shared logs.
"""

from __future__ import annotations

import time

from mykhaya.config import get_settings
from mykhaya.notifications.push import _build_apns_bearer, resolve_apns_config


def main() -> None:
    settings = get_settings()
    config = resolve_apns_config(settings)
    if not config.configured:
        raise SystemExit("APNs provider-token configuration is incomplete")

    issued_at = int(time.time())
    topic = config.bundle_id or "app.mykhaya.mobile"
    bearer = _build_apns_bearer(config, issued_at=issued_at, topic=topic)

    print("WARNING: This JWT is a temporary APNs credential. Do not paste it into chat or logs.")
    print(f"key_id={config.key_id}")
    print(f"team_id={config.team_id}")
    print(f"iat={issued_at}")
    print("algorithm=ES256")
    print("endpoint_environment=production")
    print(f"jwt={bearer}")


if __name__ == "__main__":
    main()
