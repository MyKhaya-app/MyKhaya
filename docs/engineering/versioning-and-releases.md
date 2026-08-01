# Versioning and Releases

`VERSION` is the single authoritative MyKhaya version and uses semantic versioning. Components and image metadata must use the same value.

The validator checks only that:

- `VERSION` exists and is valid semantic versioning;
- component manifests match `VERSION`;
- a release tag, when present, is exactly `v<VERSION>`.

Version validation is branch-independent. Neither `dev` nor `main` requires a special suffix.

The release-validation workflow runs for version tags or by manual dispatch. It validates and builds but never publishes, creates a release, tags a commit or deploys. Anthony performs all release actions manually after reviewing `dev` and merging it to `main`.
