# Administrative Network Boundary

Requests to `/api/v1/platform/*` must use the configured admin hostname and originate inside `MYKHAYA_ADMIN_ALLOWED_NETWORKS`. Production configuration refuses to start when the allow-list is absent or empty. A denied request receives a generic 404.

FastAPI starts with the socket peer. It ignores `X-Forwarded-For` unless that peer belongs to `MYKHAYA_TRUSTED_PROXY_CIDRS`. For a trusted peer it walks the forwarded chain from right to left and stops at the first untrusted address. Caddy is the only expected trusted peer and supplies the client chain; the API must not be directly exposed.

Configure the exact Compose/Caddy network range, not all private space. Then configure operator source ranges separately. Local container networking may require adding the Docker gateway subnet to the development allow-list.

An allow-list is defence in depth, not identity. Production should also use a VPN or identity-aware gateway, hardware-backed MFA, managed devices and alerts.
