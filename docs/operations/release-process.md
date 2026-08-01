# Release Process

## Codex handoff

1. Develop on `dev`.
2. Run Quality, Security and migration validation.
3. Confirm one Alembic head and document rollback constraints.
4. Report the exact commit and whether `dev` is ready.

## Anthony's release actions

1. Review `dev` and its passing checks.
2. Merge `dev` into `main` manually.
3. Confirm `main` checks pass.
4. Create tag `v<VERSION>` on the intended `main` commit.
5. Run or review release validation.
6. Deploy the tagged revision manually.

No workflow creates a tag, GitHub Release, merge or deployment automatically.
