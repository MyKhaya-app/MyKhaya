#!/usr/bin/env python3
"""Fails if the resolved Compose config (from `docker compose ... config --format
json`, piped in on stdin) does not publish a host port for the `caddy` service.

Guards against the exact regression found during the Platform Control Centre
security review: `docker compose config --quiet` only validates syntax, so a
compose combination that resolves cleanly but silently has no `ports:` for caddy
(e.g. compose.override.yml losing its port mapping, or a fresh clone never getting
one) passed CI anyway. Uses stdlib json (not PyYAML) deliberately, so this has no
extra dependency to install on a CI runner. See docs/operations/local-development.md.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "this combination"
    config = json.load(sys.stdin)
    caddy = (config.get("services") or {}).get("caddy")
    if not caddy:
        print(f"error: no 'caddy' service found in the resolved config for {label}", file=sys.stderr)
        return 1
    ports = caddy.get("ports")
    if not ports:
        print(
            f"error: caddy has no published ports in the resolved config for {label} — "
            "the stack would start but be unreachable from a browser.",
            file=sys.stderr,
        )
        return 1
    print(f"ok: caddy publishes {ports!r} for {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
