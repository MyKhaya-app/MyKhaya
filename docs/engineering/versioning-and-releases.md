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

## iOS app version and build numbers

The DEV (MyKhaya-Dev) and PROD (MyKhaya) iOS apps number their builds the same
way, independently of the release tags above:

- The version is `MAJOR.MINOR.PATCH` (for example `0.1.34`).
- The build number starts at `1` for each new version and counts up with each
  upload of that version (`0.1.34 (1)`, `0.1.34 (2)`…).
- DEV may be a version ahead of PROD while the next release is tested (DEV
  `0.1.35 (3)`, PROD `0.1.34 (1)`), but PROD is never ahead of DEV.
- Each app's widget extension always carries the app's exact version and
  build, as App Store Connect requires.

Each app's numbers live only in its own
`apps/ios-shell/ios/App/Config/Environment-<Dev|Prod>.xcconfig`
(`MARKETING_VERSION`, `CURRENT_PROJECT_VERSION`), so bumping one app never
changes the other. Before archiving, check that app's latest build in App
Store Connect and set the next number. See
[iOS DEV and PROD apps](../mobile/ios-environments.md#bumping-the-version-or-build).
