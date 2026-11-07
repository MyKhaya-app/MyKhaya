# Disposable registration E2E harness

This is local-only infrastructure for the committed candidate SHA
`31084ed2c39ae9c00eea43b531d518138491a229`. It uses synthetic credentials and an
ephemeral OAuth signing key. It never loads `.env` or production secrets.

Run from the candidate worktree:

```powershell
.\infrastructure\e2e\run-e2e.ps1
```

The script rejects the default `mykhaya` Compose project, validates the merged
configuration before startup, generates a disposable P-256 key, starts isolated
PostgreSQL/Redis/Mailpit/API/web/provider services, installs Chromium/WebKit,
runs Playwright, and removes only the selected project with `down -v
--remove-orphans`.

The provider signs JWTs with an ephemeral RSA key, exposes JWKS only on the
E2E network/API path, consumes authorization codes once, and preserves the
application's normal issuer, audience, nonce, expiry and signature validation.
It is not real Apple or Google acceptance.

The repository still needs dedicated E2E fixture seeding and specs for legal
versions, Beta invitations, MFA completion, account decisions, Profile and
Security. Until those are added, the stack is infrastructure-only and must not
be reported as six-journey acceptance.
