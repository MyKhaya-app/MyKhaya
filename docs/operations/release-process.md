# Release Process

## Codex handoff

1. Develop on `dev`.
2. Run `make release-check` — the single canonical local command covering
   everything the `quality` GitHub Actions workflow validates outside of its
   own image builds: `python infrastructure/scripts/validate_version.py`,
   `python -m unittest discover -s infrastructure/tests`, Compose
   resolution/port-publish validation for all three environments, Caddy
   config validation (`Caddyfile.dev`, same image/flags as CI), the Alembic
   head count, ruff (lint + format check), canonical `mypy mykhaya`, `tsc`,
   `eslint`, the backend/frontend test suites, and the frontend Docker
   `check` build target. This exists specifically so a
   release candidate can never be reported green locally while
   `python infrastructure/scripts/validate_version.py` (or any of the other
   steps it wraps) would immediately fail in CI — see the "quality /
   application" workflow for the authoritative step list.
3. Run `make security-check` — the Docker/network-heavy scanner suite,
   deliberately kept out of `release-check` so every-commit local runs stay
   fast. Mirrors the parallel jobs in `.github/workflows/security.yml`
   one-for-one (same images, flags, and pinned versions): Gitleaks
   full-history secret scan, `pip-audit`, Trivy filesystem HIGH/CRITICAL,
   Semgrep OWASP Top Ten, Checkov (Dockerfile + GitHub Actions), and Syft
   SBOM generation.
4. **Both `make release-check` and `make security-check` must pass before a
   candidate is reported ready** — neither alone is sufficient. Do not claim
   release readiness on the strength of `release-check` alone.
5. Confirm one Alembic head (covered by `make release-check`) and document
   rollback constraints.
6. Report the exact commit and whether `dev` is ready.

The closure validation basis was DEV commit `9a8e6eee13232f8405c7c6eef01d9444054c0325`, plus the uncommitted remediation changes listed in the handoff. This is working-tree evidence, not a claim about a remote GitHub SHA until the changes are committed and CI reruns.

The stable-release workflow installs the repository-pinned Node `22.23.4` and
pnpm `10.14.0` toolchain before invoking the existing Make targets. This keeps
tag validation equivalent to the normal quality workflow; it does not remove or
weaken any application, migration, build or security gate.

Migration `0125_service_monitoring` has a deliberate downgrade limitation:
its downgrade removes monitoring-created incidents and incident updates with
no administrator author before restoring the historical non-null constraints.
Production rollback is therefore backup/forward-recovery based; do not run an
Alembic downgrade against live production data merely to force older code to
run.

Current release evidence must distinguish repository/CI results from operator
evidence. Production provider settings, branch protection, deployed SHAs,
backup restore results and live monitoring remain unverified until an
authorised operator records them.

## Anthony's release actions

1. Merge approved `dev` into `main`.
2. Confirm main CI passes.
3. Create GitHub Release/tag `vX.Y.Z` on the intended main commit.
4. On production run `make prod-update RELEASE=vX.Y.Z`.
5. Confirm the reported deployed tag, SHA and health checks.

The GitHub release tag is the production version source of truth and becomes the
application version. Development always reports version `dev` and channel
`development`; the commit SHA provides exact code traceability. Runtime code
does not query GitHub for version information. No separate `VERSION`-file bump is
required before creating a release.

No workflow creates a tag, GitHub Release, merge or deployment automatically.
