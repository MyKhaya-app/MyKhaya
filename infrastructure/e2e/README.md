# Disposable registration E2E harness

This is local-only infrastructure for the committed candidate SHA
`31084ed2c39ae9c00eea43b531d518138491a229`. It uses synthetic credentials and an
ephemeral OAuth signing key. It never loads `.env` or production secrets.

Run from the candidate worktree:

```powershell
.\infrastructure\e2e\run-e2e.ps1 -BrowserProject chromium
.\infrastructure\e2e\run-e2e.ps1 -BrowserProject webkit
.\infrastructure\e2e\run-e2e.ps1 -BrowserProject mobile
```

Run one browser project per invocation, so each gets a fresh stack. Without
`-BrowserProject`, Playwright runs the three projects at the same time against
one stack. The synthetic provider hands out profiles from a single
per-provider sequence, so concurrent journeys reuse each other's synthetic
accounts and MFA mail and time out (seen 2026-11-08: all three Google journeys
failed together, while each project passed on its own). Launch the script as
its own process (`powershell -File ...`). Piping its output with `*>&1` in
Windows PowerShell 5.1 turns Docker's normal stderr progress into terminating
errors.

The script rejects the default `mykhaya` Compose project, validates the merged
configuration before startup, generates a disposable P-256 key, starts isolated
PostgreSQL/Redis/Mailpit/API/web/provider services, installs Chromium/WebKit,
runs Playwright, and removes only the selected project with `down -v
--remove-orphans`.

The provider signs JWTs with an ephemeral RSA key, exposes JWKS only on the
E2E network/API path, consumes authorization codes once, and preserves the
application's normal issuer, audience, nonce, expiry and signature validation.
It is not real Apple or Google acceptance.

The provider image has a `HEALTHCHECK` that reads the internal JWKS endpoint
(Python standard library only, as the non-root user on the read-only
container). It never calls `/authorize` or the token endpoint, so it cannot
change the synthetic profile sequence or consume authorization codes. See
[CI security scanning and validation](../../docs/engineering/ci-security-scanning.md).

The repository still needs dedicated E2E fixture seeding and specs for legal
versions, Beta invitations, MFA completion, account decisions, Profile and
Security. Until those are added, the stack is infrastructure-only and must not
be reported as six-journey acceptance.
