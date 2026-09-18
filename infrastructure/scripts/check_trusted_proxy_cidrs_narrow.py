#!/usr/bin/env python3
"""Fails if the resolved Compose config's MYKHAYA_TRUSTED_PROXY_CIDRS for the
`api` service is wider than a single host (/32 IPv4, /128 IPv6), piped in on
stdin as `docker compose ... config --format json`.

Guards against the exact regression this check was written after: trusting
the whole `edge`/`app` Docker network subnet instead of Caddy's own pinned
address inside it. `edge` is non-internal (it needs a real gateway for
api/worker/scheduler's outbound SMTP/Web Push/APNs/FCM traffic), and that
gateway address is what Docker's own NAT makes every host-published-port
request appear to originate from — a subnet-wide trust boundary treats it as
just another trusted hop and lets a forged X-Forwarded-For chain walk
straight past it to an attacker-supplied value. See "Trusted-proxy boundary"
in docs/architecture/deployment-model.md for the full story.

Local-dev-only by design: this is not run against the production compose
combination, whose MYKHAYA_TRUSTED_PROXY_CIDRS/MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS
describe a different (NetBird) topology validated separately by its own
operator, not a Docker Compose network this repo controls the shape of.
"""

from __future__ import annotations

import ipaddress
import json
import sys


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "this combination"
    config = json.load(sys.stdin)
    api = (config.get("services") or {}).get("api")
    if not api:
        print(f"error: no 'api' service found in the resolved config for {label}", file=sys.stderr)
        return 1
    raw = (api.get("environment") or {}).get("MYKHAYA_TRUSTED_PROXY_CIDRS")
    if not raw:
        print(f"error: api has no MYKHAYA_TRUSTED_PROXY_CIDRS in the resolved config for {label}", file=sys.stderr)
        return 1
    try:
        cidrs = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: MYKHAYA_TRUSTED_PROXY_CIDRS is not valid JSON for {label}: {raw!r}", file=sys.stderr)
        return 1
    wide = []
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr, strict=False)
        if network.prefixlen != network.max_prefixlen:
            wide.append(cidr)
    if wide:
        print(
            f"error: MYKHAYA_TRUSTED_PROXY_CIDRS for {label} trusts whole subnet(s) "
            f"{wide!r}, not single pinned host(s) — see docs/architecture/"
            "deployment-model.md's 'Trusted-proxy boundary' section for why this "
            "must stay a /32 (or /128) per trusted proxy in local development.",
            file=sys.stderr,
        )
        return 1
    print(f"ok: MYKHAYA_TRUSTED_PROXY_CIDRS for {label} is host-only: {cidrs!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
