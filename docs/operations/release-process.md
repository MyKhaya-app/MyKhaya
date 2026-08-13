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
   `check`/`mobile-check` build targets. This exists specifically so a
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

## Anthony's release actions

1. Review `dev` and its passing checks.
2. Merge `dev` into `main` manually.
3. Confirm `main` checks pass.
4. Create tag `v<VERSION>` on the intended `main` commit.
5. Run or review release validation.
6. Deploy the tagged revision manually.

No workflow creates a tag, GitHub Release, merge or deployment automatically.
