# Versioning and Releases

## Single source of truth

The repository `VERSION` file is the authoritative application version source.

Current initial development version:

- `0.1.0-dev`

Components consume this version through runtime/build plumbing instead of independently maintained hard-coded version strings.

## Semantic versioning

MyKhaya uses semantic versioning:

- `MAJOR.MINOR.PATCH`

Stable tags use a `v` prefix:

- `v0.1.0`

Development versions use:

- `MAJOR.MINOR.PATCH-dev`
- Optional metadata: `MAJOR.MINOR.PATCH-dev+<build>`

While MyKhaya is pre-`1.0.0`, releases remain below `1.0.0` unless an explicit product decision is made.

## Build metadata fields

Safe runtime metadata fields:

- `version`
- `commit`
- `build_time`
- `environment`
- `channel`

These are provided by `/api/v1/health/build` and surfaced in the Platform Control Centre system information.

The public status page must not expose exact version, commit or internal release details.

## Validation controls

The `version-validation` workflow enforces:

- valid version format
- branch-specific version policy (`dev` requires `-dev`, `main` requires stable)
- stable tag format (`vMAJOR.MINOR.PATCH`)
- tag/version match
- non-regression versus latest stable tag
- component version-resolution alignment
- single Alembic head check

## Release channels

- Development channel: source branch `dev`, tags like `mykhaya:dev` and optional `mykhaya:dev-<sha>`
- Stable channel: source branch `main` and stable tags; `latest` moves only after approved stable release

If registry publishing is introduced, it must remain controlled and traceable, and development images must never be published as `latest`.