# CI security scanning and validation

This explains how the CI security scanners run, how a finding is triaged and
recorded, and the full procedure for validating a release candidate.

`.github/workflows/quality.yml` and `.github/workflows/security.yml` run on
pushes to `dev`, `main` and `release/**`, and on pull requests to `dev` and
`main`. Locally, `make release-check` mirrors the quality workflow and
`make security-check` mirrors the security workflow one-for-one: same images,
flags and pinned versions (see
[Release process](../operations/release-process.md)). Treat GitHub Actions as
the final authority. A candidate is not CI-clean until both workflows pass on
its exact SHA.

## Scanners

| Job | Tool (pinned) | Scope | Fails on |
|---|---|---|---|
| `secrets` | Gitleaks v8.28.0 | Full Git history of **every ref the checkout fetched** (`fetch-depth: 0` fetches all branches and tags) | Any finding not listed in `.gitleaksignore` |
| `python-dependencies` | pip-audit | `apps/api` dependencies | Known vulnerable package |
| `filesystem` | Trivy 0.64.1 | Repository files, vulnerability and misconfiguration | HIGH or CRITICAL |
| `semgrep` | Semgrep 1.172.0, `p/owasp-top-ten` | `apps/` | Any finding |
| `checkov` | Checkov 3.2.451 | Dockerfiles and GitHub Actions | Any failed check |
| `sbom` | Syft v1.30.0 | Repository | Generation error |
| `security-gate` | — | Aggregates the jobs above | Any job not successful |

Because Gitleaks scans every fetched ref, a release branch's security run can
report a finding that exists only on another branch (for example `dev`). The
candidate's `.gitleaksignore` must then carry that fingerprint too.

## Triage

Never print or paste a detected value. Reproduce with `--redact` and a JSON
report written outside the repository, then classify from metadata (rule, file,
line, commit, branches containing it, value length and shape, known live-key
prefixes, and whether the same value appears in any real `.env`). For each
finding, decide:

1. **Genuine credential.** Stop. Do not commit or push CI changes. Record the
   service and exposure scope without the value. The service owner must revoke
   or rotate it. Rewriting history needs separate approval. An ignore entry
   never substitutes for rotation.
2. **Synthetic fixture or false positive.** Prefer a source fix where it removes
   the finding (for example a generated per-run value). Findings in commits that
   are already pushed cannot be removed without rewriting history, so they get
   an exact fingerprint in `.gitleaksignore`.

`.gitleaksignore` entries are exact `commit:file:rule:line` fingerprints, each
under a comment that says why it is safe. Never add path-wide, rule-wide or
directory-wide exclusions, a `.gitleaks.toml` allowlist, or `--no-git`.

### Recorded dispositions (2026-11-08, candidate `f1dacd5`)

| # | Rule | Location (commit) | Where | Classification | Live access | Action |
|---|---|---|---|---|---|---|
| 1–5 | `generic-api-key` | `compose.e2e.yml` lines 45, 57, 73, 94, 111 (`6d5f78c`) | Current tree and history (release branch only) | Synthetic E2E `MYKHAYA_SECRET_KEY`, explicitly labelled "e2e"/"synthetic", used only by the disposable E2E stack (`MYKHAYA_ENVIRONMENT=development`). Not in any real `.env`. | None | Five exact fingerprints. No rotation. |
| 6 | `generic-api-key` | `apps/api/tests/test_billing_config.py` line 131 (`bc22202`) | History on `dev` only, not in the candidate's history | The already-reviewed SEC-18 synthetic Stripe placeholder (documented placeholder suffix, far too short to be a Stripe key), moved to a new line on `dev` | None | One exact fingerprint. No rotation. |

## Synthetic fixture conventions

- Make synthetic values obviously synthetic: include `synthetic`, `e2e`,
  `test` or a documented placeholder suffix (`abc123`, `xyz123`, `db123`). Never
  use the shape of a real key's random payload.
- Generate a value at runtime when a test only needs uniqueness (for example
  per-run passwords, provider subjects and keys). The E2E OAuth provider
  generates its RSA signing key at start-up.
- Never reuse a real deployment's value in a fixture, compose file or example
  file. Synthetic stacks must not load the repository `.env`.
- A new synthetic literal that Gitleaks flags gets its own fingerprint and
  rationale in the same change, never a broader exclusion.

## Container health checks

Checkov `CKV_DOCKER_2` requires a `HEALTHCHECK` in every Dockerfile. A health
check must test genuine readiness using only what the image already contains,
run as the image's non-root user on a read-only root filesystem, and must not
change application or test state.

The E2E OAuth provider (`infrastructure/e2e/Dockerfile.oauth-provider`) checks
its internal JWKS endpoint with the Python standard library. It is healthy only
when the synthetic signing key (`kid` `synthetic-e2e-key`) is served. It never
calls `/authorize` (which advances the synthetic profile sequence) or the token
endpoint (which consumes codes). Timing: interval 10s, timeout 3s, start
period 10s, 3 retries. Verified 2026-11-08: healthy in about 8s as user
`65532:65532` with `--read-only`, and unhealthy (exit 1) when the provider
process is not running.

## Release-candidate validation procedure

1. Confirm the workspace HEAD and the remote branch SHA. The tree must be clean
   apart from the reviewed change.
2. `make release-check`. This is the quality workflow: version validation,
   infrastructure tests, Compose and Caddy validation, a single Alembic head,
   ruff, format, mypy, `eslint .`, `tsc`, backend and frontend tests and the
   frontend `check` build.
3. `make security-check`. This must run in a real clone with full history,
   because a linked worktree's `.git` file is not visible inside the Gitleaks
   container ("0 commits scanned" means the scan did not run). To match CI, scan
   a fresh clone of the GitHub repository at the candidate SHA, so every remote
   branch is included.
4. API tests run in an isolated, fresh test stack
   (`infrastructure/scripts/run-tests.sh`). Reruns against the same database
   are not equivalent (see [Known test debt](test-debt.md)).
5. The migration rollback smoke test and production image builds run in the
   quality workflow on Linux. Report them as unverified if they were not run
   locally.
6. Push only after steps 1–3 pass. Then confirm both workflows on the exact SHA
   from the push-event run list
   (`gh run list --branch <branch> --event push`), not from a pull-request
   query.

## Known limitations

- Gitleaks scans every ref fetched by CI, so other branches' history can fail a
  release branch's `secrets` job.
- `make release-check` and `make security-check` are POSIX make targets. On
  Windows, run the equivalent Docker commands from the workflow files, or use
  WSL.
- The E2E harness (`infrastructure/e2e/run-e2e.ps1`) needs Docker plus
  Playwright browsers. It is not part of either CI workflow. Run it once per
  browser project (`-BrowserProject chromium|webkit|mobile`). Concurrent
  projects share one synthetic provider profile sequence and fail (see the
  [E2E README](../../infrastructure/e2e/README.md)).
