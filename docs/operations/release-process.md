# Release Process

## Codex handoff

1. Develop on `dev`.
2. Run `make release-check` — the single canonical local command covering
   everything the `quality` GitHub Actions workflow validates outside of its
   own image builds: `python infrastructure/scripts/validate_version.py`,
   `python -m unittest discover -s infrastructure/tests`, Compose
   resolution/port-publish validation for all three environments, the
   Alembic head count, ruff, canonical `mypy mykhaya`, `tsc`, `eslint`, and
   the backend/frontend test suites. This exists specifically so a release
   candidate can never be reported green locally while
   `python infrastructure/scripts/validate_version.py` (or any of the other
   steps it wraps) would immediately fail in CI — see the "quality /
   application" workflow for the authoritative step list.
3. Run the exact Gitleaks command from `.github/workflows/security.yml`
   locally (`docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:<pinned
   version> detect --source=/repo --no-banner`) — `make release-check`
   deliberately does not run this (it needs Docker network access to pull
   the Gitleaks image and is slow), but it must still be run and pass before
   calling a candidate ready.
4. Confirm one Alembic head (covered by `make release-check`) and document
   rollback constraints.
5. Report the exact commit and whether `dev` is ready.

## Anthony's release actions

1. Review `dev` and its passing checks.
2. Merge `dev` into `main` manually.
3. Confirm `main` checks pass.
4. Create tag `v<VERSION>` on the intended `main` commit.
5. Run or review release validation.
6. Deploy the tagged revision manually.

No workflow creates a tag, GitHub Release, merge or deployment automatically.
