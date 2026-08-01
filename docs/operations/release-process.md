# Stable Release Process

## Preconditions

- Release pull request from `dev` to `main`
- Quality and security workflows passing
- Version in `VERSION` updated from `*-dev` to stable `MAJOR.MINOR.PATCH`
- Migration review complete

## Standard release flow

1. Merge validated work into `dev`.
2. Prepare release by setting `VERSION` to the intended stable value.
3. Open release pull request from `dev` to `main`.
4. Merge after approval and required checks.
5. Create tag `vMAJOR.MINOR.PATCH` from the resulting `main` commit.
6. Run the manual `stable-release` workflow with that tag.
7. Generate GitHub release notes.
8. Promote deployment artifacts built from that exact tag.
9. Move `dev` forward to next development version (for example `0.2.0-dev`).

## Traceability requirements

Every stable release must be traceable to:

- merged commit
- release pull request
- `VERSION` value
- stable tag
- workflow run
- built artifact set

## Database migration safety

For each stable release, record:

- current database revision
- target database revision
- whether migration is required
- rollback considerations

Before release approval:

- verify migration ordering
- ensure one Alembic head
- test migration from previous stable state
- identify irreversible steps
- avoid immediate destructive schema assumptions