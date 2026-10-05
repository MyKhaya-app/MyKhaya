# Versioning and Releases

GitHub release tags are the authoritative production version and use semantic
versioning with a leading `v`. Development deployments report version `dev`.
Component package versions remain independent packaging metadata.

The validator checks only that:

- a release tag follows `vMAJOR.MINOR.PATCH`, with optional SemVer prerelease or
  build metadata;
- stable build metadata uses the release tag as `MYKHAYA_VERSION`;
- development build metadata uses `MYKHAYA_VERSION=dev` and channel `development`.

Version validation is branch-independent. Neither `dev` nor `main` requires a special suffix.

The release-validation workflow runs for `v*` tags or by manual dispatch. It
validates and builds but never publishes, creates a release, tags a commit or
deploys. Anthony performs all release actions manually after reviewing `dev`
and merging it to `main`.
