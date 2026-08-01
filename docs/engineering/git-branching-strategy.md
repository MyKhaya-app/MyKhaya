# Git Branching Strategy

MyKhaya uses two permanent branches:

- `main`: stable production branch only
- `dev`: active development and integration branch

## Branch purposes

`dev` contains features, fixes, documentation, migrations and security work that is still being validated.

`main` contains intentionally promoted, production-ready changes that passed quality and security checks.

Do not develop directly on `main` during normal work.

## Working branches

- `feature/*`
- `fix/*`
- `security/*`
- `docs/*`
- `hotfix/*`

Normal pull requests target `dev`.

Release pull requests target `main`.

Hotfix pull requests target `main`, then the same hotfix must be merged back into `dev`.

## Promotion flow

1. Build and validate work in short-lived branches.
2. Merge into `dev` through pull requests.
3. Stabilize and prepare release.
4. Open release pull request from `dev` to `main`.
5. Merge after checks and review.
6. Tag the merge commit with `vMAJOR.MINOR.PATCH`.

`main` should remain the public default branch because it is the stable baseline for external readers and production operations.