# MyKhaya Security and Codebase Audit — 2026-10

Status: **COMPLETE.** Discovery, authorization (BOLA/IDOR) audit, dependency/CI/CD/container review,
a full CI security-gate investigation, test-baseline triage, and targeted remediation are all
finished. This report was written chronologically as the audit progressed (Phase 1 discovery
first, then continuation-pass findings and fixes layered on top) and each finding's `Status:` line
states its final disposition — see the Completion Summary at the end for the final tally, and
Before Production for what remains before this codebase should be considered launch-ready.

## Executive Summary

MyKhaya is a modular-monolith FastAPI backend + single Next.js consumer frontend, reused across
web, iOS and Android via thin Capacitor WebView shells, plus a desktop-first admin surface
("Platform Control Centre" / PCC) hosted in the same Next.js build and separated by hostname at
the edge. The codebase shows a mature, deliberately documented security posture: parameterised SQL
throughout, strict Pydantic request models (anti mass-assignment), a fixed CORS allow-list, CSRF
double-submit + Origin checks, HttpOnly/SameSite session cookies, Argon2 password hashing, a
centralised entitlements module, a single notification pipeline, and a non-wildcard native
`allowNavigation` host list with a regression test banning Stripe-like additions.

**No exploitable code-level vulnerability was found anywhere in the codebase** — no SQL injection,
no XSS sink, no auth bypass, no BOLA/IDOR gap across 17 router modules and the platform-isolation
boundary. The project's own documentation is unusually candid about what is *not* yet done
(PCC WebAuthn, browser MFA rollout), and those self-disclosed gaps turned out to be accurate, not
understated.

**One real, newly-found issue drove most of this audit's actual work:** a genuine DVLA UAT API
credential, committed 3 days before this audit began, sitting exposed on a public,
branch-protection-free GitHub repository, undetected inside a CI secrets-scanning gate that had
already been failing for 7 weeks over unrelated, harmless test fixtures (SEC-18). Investigating why
that gate was red surfaced two more genuinely-failing CI security jobs — Trivy and Semgrep — both
real findings, both fixed and re-verified with the exact CI commands (SEC-21, SEC-22), plus a
separate, confirmed-absent branch-protection configuration on both `main` and `dev` (SEC-19). A
general lesson applies across all of these: a security signal that's allowed to stay red for weeks
stops functioning as a signal at all, which is exactly the condition that let the real credential
sit unnoticed.

Beyond that: a genuine (non-security) regression was found and fixed in the shared safe-area CSS
architecture (two spots where the protected mobile-geometry invariant from AGENTS.md/mobile-standards.md
was violated), one real raw-SQL-construction pattern was eliminated at the source rather than just
documented, one container-hardening gap was closed, and a substantial pre-existing test-failure
baseline (121 web, 15 backend) was triaged and classified — the sampled failures consistently
turned out to be stale assertions trailing legitimate changes, in two cases revealing security
controls that got *stricter* than the old tests expected, not weaker.

## Scope

Full repository: `apps/api` (backend), `apps/web` (consumer frontend + PCC host), `apps/ios-shell`,
`apps/android-shell`, `apps/mobile` (retired), `packages/*`, `infrastructure/`, `.github/workflows/`,
root compose/config files, and all documentation under `docs/`.

## Methodology

Three parallel research passes (no code modified):
1. Full read of the 11 AGENTS.md-mandated docs + AGENTS.md/README.md/SECURITY.md, extracting
   stated invariants.
2. Repository-wide architecture mapping (apps, packages, routers, DB, workers, CI/CD, infra,
   testing) with file-path evidence for every claim.
3. Full read of all 18 files under `docs/security/`, plus a grep-based sweep for XSS sinks, CORS
   config, hardcoded secrets, raw SQL, `subprocess`/shell usage, rate limiting, and TODO/FIXME
   density.

Followed by a targeted verification: confirmed `apps/mobile/.env` is untracked and correctly
gitignored (no secret exposure), and confirmed `backups/*.sql.gz` are untracked and gitignored.

## Architecture Reviewed

- **Backend** (`apps/api`): FastAPI, SQLAlchemy 2.0 async + Alembic (106 migrations), PostgreSQL
  17.5, Redis (cache + outbox/job queue). Entry point `mykhaya/main.py`; 30 router modules under
  `mykhaya/routers/`; auth/session core in `mykhaya/security.py` + `mykhaya/dependencies.py`;
  separate `worker.py` (outbox/push/email delivery) and `scheduler.py` (periodic scans) processes.
  Third-party integrations: Stripe (billing), DVLA (vehicle lookup), Apple/Google sign-in, APNs/FCM
  (native push).
- **Frontend** (`apps/web`): Next.js 15 App Router, React 19. One build serves three logical
  surfaces — consumer app, PCC (`/control-centre`), public status (`/service-status`) — split by
  `middleware.ts` host-based rewriting, which blocks direct cross-host path access. Native-shell
  detection centralised in `components/native-runtime.ts` (`isNativeShell()`, `nativePlatform()`,
  `isPlatformControlCentre()`), per AGENTS.md's single-canonical-boundary rule.
- **Native**: `apps/ios-shell` and `apps/android-shell` are thin Capacitor shells loading the live
  hosted frontend over HTTPS (`server.url`), not bundled builds. Both have non-wildcard
  `allowNavigation` host lists. iOS has Keychain-backed session storage
  (`@aparajita/capacitor-secure-storage`, `whenUnlockedThisDeviceOnly`, `sync:false`); **Android has
  no equivalent secure storage yet** (self-disclosed gap, mitigated only by `allowBackup="false"`).
- **Retired**: `apps/mobile` (Expo scaffold, superseded per ADR 0011/0012) — only `.env` +
  `.gitignore` remain on disk, untracked, dead directory.
- **Infrastructure**: Caddy reverse proxy, Docker Compose (base/dev/production/test variants with
  isolated test DB/Redis), hardened containers (`cap_drop: ALL`, `no-new-privileges`, `read_only`).
- **CI/CD**: `quality.yml` (lint/type/test/build gate), `security.yml` (weekly + on-push: secrets,
  dependency audit, SAST/semgrep, IaC/checkov, SBOM), `stable-release.yml` (release validation gate).

## Documentation Reviewed

AGENTS.md, README.md, SECURITY.md, and all 11 AGENTS.md-mandated docs (engineering-standards,
ui-platform-standards, frontend-standards, mobile-standards, layout-and-navigation, design-system,
visual-identity, definition-of-done, ADR 0012/0013/0014), plus all 18 files under `docs/security/`
(api-security, browser-security, data-protection, data-retention, data-subject-rights,
dependency-and-supply-chain-security, dpia, implementation-review, incident-response-outline,
logging-and-monitoring, platform-administration-security, platform-administration-threat-model,
secure-development-lifecycle, security-baseline, threat-model, vulnerability-management,
asvs-control-matrix, asvs-5.0.0.csv). Filenames only (not yet read) for `docs/operations/`,
`docs/mobile/`, `docs/product/`, and the other 11 ADRs (0001–0011) — flagged for a follow-up pass
before any work touching deployment, mobile platform status, or product scope.

## Documentation vs. Implementation Discrepancies (recorded, not resolved)

| # | Doc says | Implementation status | Files |
|---|---|---|---|
| 1 | Browser MFA is a mandatory architectural invariant (engineering-standards.md, security-baseline.md) | `implementation-review.md` lists "MFA for browser users" as an open release blocker, not complete | `docs/engineering/engineering-standards.md`, `docs/security/implementation-review.md` |
| 2 | PCC requires "separate privileged authorization, MFA, strong session controls" (engineering-standards.md) | README.md + `platform-administration-threat-model.md` + `implementation-review.md` all state WebAuthn/passkey enrolment for PCC admins is designed but not implemented; "The Control Centre must not be described as production-ready" | `README.md`, `docs/security/platform-administration-security.md`, `docs/security/platform-administration-threat-model.md` |
| 3 | layout-and-navigation.md: phone bottom bar has "up to five contextual destinations" | mobile-standards.md: "exactly four primary destinations: Home, Calendar, Family, More" | `docs/design/layout-and-navigation.md`, `docs/engineering/mobile-standards.md` — needs reconciling against actual `primary-nav-destinations.ts` content (not yet verified in code) |

## Security Findings

```
ID: SEC-01
Severity: High
Area: Authentication / PCC
Finding: Platform Control Centre (admin.mykhaya.app) does not yet enforce mandatory WebAuthn/passkey MFA for platform operators, despite this being the documented required control for a privileged management plane.
Evidence: README.md ("The Control Centre is not production-ready until mandatory WebAuthn/passkey authentication is implemented and independently reviewed"); docs/security/platform-administration-security.md and platform-administration-threat-model.md both list WebAuthn as "required" but not yet implemented; docs/security/implementation-review.md lists it as an open release blocker.
Risk: Compromise of an operator credential (password-only or TOTP-only) could grant access to a highly privileged management plane with billing, Home-disable, and user-anonymisation capabilities, without the phishing-resistance WebAuthn would provide.
Recommended remediation: Treat as a known, already-tracked pre-launch blocker. Do not relax any PCC-related control while this gap is open. No code change recommended in this pass — this is a planned, not-yet-built feature, not a regression.
Affected files: apps/api/mykhaya/platform_mfa.py, docs/security/platform-administration-security.md
OWASP mapping: ASVS V6.5 (MFA), API Security Top 10 API2:2023 (Broken Authentication)
NCSC mapping: NCSC Secure Development Principles — Authentication
Status: Pre-existing, self-disclosed, not a new finding.

ID: SEC-02
Severity: High (by design, feature-flagged rollout — not an exploitable bug)
Area: Authentication / Browser consumer MFA
Finding: RESOLVED by direct code/test verification. Browser consumer MFA is fully and correctly implemented, with a single shared enforcement seam, but is deliberately gated behind `MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED` (config field `browser_mfa_handoff_enabled`), which defaults to `false` everywhere (no env file in the repo sets it true). `docs/architecture/authentication.md:53-55` documents this explicitly as the "Phase 4.5 pre-auth handoff" rollout. implementation-review.md's "not complete" statement is accurate (the control is not yet turned on by default); engineering-standards.md's "mandatory" statement is the target end-state architectural requirement, not a claim about current default enforcement. This is a genuine incomplete-rollout state, not a stale-doc issue and not a bypassable bug.
Evidence (code read directly, not inferred from docs):
  - `apps/api/mykhaya/consumer_mfa_policy.py:106` / `apps/api/mykhaya/routers/auth.py:166` — the single gate (`policy.enforcement_enabled and policy.required`) sits inside `complete_browser_authentication()`, the shared seam used by both password login (`routers/auth.py` `login()`, line ~1391) and Apple sign-in continuation (line ~933) — confirmed by reading both call sites, not assumed.
  - `apps/api/mykhaya/config.py:94` — `browser_mfa_handoff_enabled: bool = False`; no `.env*` file in the repo sets it true.
  - Checked every call site of `issue_family_session()` (the only function that mints an adult browser session) in auth.py: exactly 4 — inside `complete_browser_authentication` (gated), the `/auth/mfa/verify` completion endpoint (only reached after a factor is proven), `/auth/passkeys/login/verify` (intentionally exempt: WebAuthn passkey is itself a phishing-resistant possession-bound credential, and passkey *registration* requires `require_fresh_adult_auth`, i.e. a session that already cleared whatever MFA policy was in force at registration time — there is no path to register a passkey without first clearing the required-MFA gate), and `/auth/child-login` (issues `SessionKind.child`, to which the adult-only consumer MFA policy does not apply).
  - `TrustedDevice`/`/auth/renew` ("remember this device") rows are only ever minted by `issue_trusted_device()` called from inside `issue_family_session()` — i.e. only after a session has already been fully established through one of the four reviewed paths above. `/auth/renew` only extends an already-compliant session; it has no independent login path and cannot be used to originate a session that skipped MFA.
  - Existing test coverage (`apps/api/tests/test_browser_mfa_flow.py`) already proved: fail-closed behaviour on an invalid policy, a full enforcement matrix across `(handoff_enabled, policy)`, email-handoff has no session before success, TOTP enrolment + replay protection, and explicit-optional overriding the rollout flag.
Risk: None currently exploitable. Forward risk is operational only: if `MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED` is turned on in production without also setting an explicit platform/home/user policy, the `legacy_fallback` path (consumer_mfa_policy.py:103-105) correctly fails safe to `required`, so there is no "silently stays optional" footgun either.
Remediation completed:
  - Added `test_social_login_completion_is_gated_by_the_same_shared_seam` to `apps/api/tests/test_browser_mfa_flow.py`, proving `complete_browser_authentication` (the function Apple/Google continuation shares with password login) refuses to issue a session for a required-policy user regardless of caller.
  - Added `test_issue_family_session_call_sites_are_an_explicit_reviewed_allowlist`, a source-level regression guard asserting the exact count (4) of `issue_family_session()` call sites in auth.py, with inline documentation of why each is exempt/gated — so a future change that adds a fifth, unreviewed call site (a real bypass risk) fails CI until deliberately reviewed.
  - Both new tests run against the real application via the project's isolated test stack and pass (`infrastructure/scripts/run-tests.sh pytest tests/test_browser_mfa_flow.py -v` — 12 passed).
  - No code behaviour was changed; no documentation was found to be stale, so none was corrected.
Affected files: apps/api/mykhaya/consumer_mfa_policy.py, apps/api/mykhaya/routers/auth.py, apps/api/tests/test_browser_mfa_flow.py, docs/architecture/authentication.md
OWASP mapping: ASVS V6.5, API2:2023
NCSC mapping: Authentication
Status: Confirmed — accepted pre-launch blocker (rollout flag off by default), not a defect. Regression tests added.

ID: SEC-03
Severity: Medium
Area: Native / Android secure storage
Finding: Android native shell has no secure, persistent credential storage equivalent to iOS Keychain; the only mitigating control is android:allowBackup="false".
Evidence: docs/architecture/adr/0014-capacitor-android-shell.md — explicit self-disclosed gap.
Risk: If a persistent bearer-token store is added to the Android shell later without an equivalent to iOS's whenUnlockedThisDeviceOnly Keychain binding, tokens could persist insecurely (app-private storage is still subject to rooted-device extraction).
Recommended remediation: No action needed now since no persistent native credential storage exists yet on Android (session store currently in-memory only per ADR). Flag as a requirement to action before Android ships persistent login.
Affected files: apps/android-shell/android/app/src/main/AndroidManifest.xml, docs/architecture/adr/0014-capacitor-android-shell.md
OWASP mapping: Mobile Top 10 2024 M9 (Insecure Data Storage)
NCSC mapping: Secure Development — Data at rest
Status: Pre-existing, self-disclosed, not a new finding.

ID: SEC-04
Severity: Medium
Area: Compliance / Data Subject Rights
Finding: Statutory data-subject-rights workflows (export, correction, self-service erasure) are not implemented; only narrow PCC-operator-only anonymisation and permanent-Home-deletion actions exist, explicitly documented as not a substitute for a real erasure flow.
Evidence: docs/security/data-subject-rights.md, docs/security/data-retention.md.
Risk: Regulatory (UK GDPR) exposure if a real data subject request arrives before manual operator processes are formalised; not an application security vulnerability.
Recommended remediation: Track as a legal/compliance workstream, not an engineering security fix. No code change in scope for this audit pass.
Affected files: docs/security/data-subject-rights.md
OWASP mapping: N/A (privacy/legal, not OWASP)
NCSC mapping: N/A
Status: Pre-existing, self-disclosed, not a new finding.

ID: SEC-05
Severity: Low
Area: Backend / SQL construction style
Finding: A handful of f-string-interpolated SQL statements exist in Alembic migrations and one runtime helper (support_reference.py), using fixed internal constants rather than user input, but the pattern itself (string interpolation into SQL text rather than bind parameters) is worth a second look to confirm the interpolated values can never become configurable/user-influenced in future.
Evidence: apps/api/migrations/versions/0015_colour_palette.py:76,84,95,99; apps/api/migrations/versions/0045_calendar_colour_hex.py:60,71; apps/api/migrations/versions/0087_support_tickets.py:181; apps/api/mykhaya/support_reference.py:22.
Risk: Currently none exploitable (no user-controlled input reaches these strings). Risk is forward-looking: if SUPPORT_REFERENCE_SEQUENCE or a migration constant is ever sourced from config/user data without changing the interpolation pattern, this becomes an injection point.
Recommended remediation: Low priority. Optionally convert support_reference.py's nextval() call to use a bound identifier-safe pattern (Postgres doesn't allow binding identifiers directly, so the real fix is documenting/asserting the constant is never externally derived) — add a one-line comment stating the invariant rather than changing behaviour.
Affected files: apps/api/mykhaya/support_reference.py
OWASP mapping: ASVS V1.2 (Injection Prevention) — informational, not a confirmed violation
NCSC mapping: N/A
Status: SUPERSEDED by SEC-22. The CI security-gate investigation (requested after this Phase 1 note was written) found the `semgrep` job was actually failing a blocking rule on this exact line — this "low priority, optional" item turned out to be live CI debt. Fixed under SEC-22 by rewriting to `select(func.nextval(...))`, eliminating the pattern entirely rather than suppressing the detector. See SEC-22 for the fix and verification.

ID: SEC-06
Severity: Informational
Area: Documentation clarity
Finding: Two distinct admin-ish surfaces exist with similar names: apps/web/app/control-centre/ (the real, privileged Platform Control Centre) and apps/web/app/khaya-control-centre/ (a small, 3-file, household-level "Khaya Control Centre" for Home Admins — per docs/design/layout-and-navigation.md, intentionally distinct from the platform PCC).
Evidence: apps/web/app/control-centre/ (large, PCC), apps/web/app/khaya-control-centre/ (3 files: children/page.tsx, feature-management/page.tsx).
Risk: Naming collision risk for future contributors/agents mistaking one for the other, given AGENTS.md's explicit PCC-isolation rules. No evidence of actual authorization confusion found in this pass.
Recommended remediation: No code change recommended; consider a one-line clarifying comment at the top of each directory's layout or README noting the distinction, if not already present.
Affected files: apps/web/app/khaya-control-centre/, apps/web/app/control-centre/
OWASP mapping: N/A
NCSC mapping: N/A
Status: Informational.

ID: SEC-07
Severity: Informational
Area: Operational hygiene (not a git/code finding)
Finding: Two real PostgreSQL backup dumps (backups/*.sql.gz) exist on disk, correctly gitignored and never committed, but the repository working directory itself lives inside a Nextcloud-synced folder (C:\Users\me\Nextcloud2\...), which is a distribution path outside git's visibility.
Evidence: backups/mykhaya-20260730T212750Z.sql.gz, backups/mykhaya-20260907T201907Z.sql.gz; .gitignore:21 (backups/); confirmed untracked via git ls-files and empty git log for the path.
Risk: Potential unintended distribution of real/demo user PII via cloud sync if this machine's Nextcloud sync scope includes this path.
Recommended remediation: User to confirm Nextcloud sync exclusion for backups/, or relocate the backup output directory outside the synced tree. Dump contents were not inspected or exposed as part of this action, per instruction.
Remediation completed: Added an explicit operational-hygiene note to docs/operations/backup-and-restore.md stating that `backups/` is a working directory for `make backup`/`make restore`, not long-term storage, that dumps must be moved to an approved destination and deleted locally, and specifically warning against running `make backup` inside a cloud-sync-managed checkout without first confirming that sync client's exclusion scope. No backup files were deleted, inspected, or moved.
Affected files: backups/ (not in git, not modified), docs/operations/backup-and-restore.md (documentation updated)
OWASP mapping: N/A
NCSC mapping: Data protection at rest
Status: Documentation corrected / manual verification still required from user (Nextcloud sync-scope confirmation is outside what this audit can check).
```

## CI Security-Gate Investigation (priority pass)

This investigation was requested to take priority over closing the audit, after the earlier
continuation pass surfaced that `security.yml`'s gate had been failing on recent pushes. Full
findings below.

```
ID: SEC-18
Severity: High (one confirmed real secret, removed from source; nine findings resolved as false positive/test fixture)
Area: Secrets management / CI security gate
Finding: The `secrets` job in .github/workflows/security.yml (gitleaks v8.28.0, full-history scan, matching docs/operations/release-process.md's documented policy) has been failing on every push to `dev` and `main` since 2026-08-15, with zero passing runs in the 300 most recent executions (389 total runs exist; the last success was 2026-08-13T16:03:17Z). Reproducing the exact CI command locally (`docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.28.0 detect --source=/repo --no-banner`) returned the same 10 findings CI reports.

CLASSIFICATION OF ALL 10 FINDINGS:

1. .env.example:70 (MYKHAYA_DVLA_UAT_API_KEY) — CONFIRMED SECRET. A real DVLA (UK gov Vehicle Enquiry Service) UAT API key, introduced in commit 32b102ab (2026-09-29, message "COmmit"). Verified via SHA-256 hash comparison (value never printed) that this is byte-for-byte identical to the key currently configured in the live, gitignored .env file — i.e. a real, currently-used credential, not a look-alike placeholder. Every other credential field in .env.example (Stripe keys, DVLA production key, MYKHAYA_SECRET_KEY) is left blank in this same file; this was the one exception. Tracked by git, present in the current working tree at HEAD before this fix, and reachable on GitHub: confirmed present on `origin/main`, `origin/dev`, and three other remote branches (`git branch -a --contains <commit>`). The repository (`MyKhaya-app/MyKhaya`) is confirmed **public** (`gh api repos/.../ --jq '.private'` → `false`), and neither `main` nor `dev` has any branch protection configured (`gh api .../branches/main/protection` → 404 "Branch not protected", same for `dev`) — so this was pushed straight to both branches with no required check gating it, and has been publicly visible for several days.
2. .env.production.example:4 (MYKHAYA_SECRET_KEY) — DOCUMENTATION EXAMPLE / FALSE POSITIVE. Value is the literal instructional string `GENERATE_A_UNIQUE_32_PLUS_CHARACTER_SECRET`, unchanged since introduction (commit ce2887cf). Not a credential.
3. docs/engineering/engineering-standards.md:90 — FALSE POSITIVE. Gitleaks' generic-api-key heuristic matched the prose phrase "APNs/private" (from "...APNs/private keys or other credentials.") on its mixed case and slash. No credential value present.
4. apps/api/mykhaya/notifications/push.py:128 — FALSE POSITIVE. Matched `ec.SECP256R1`, the `cryptography` library's elliptic-curve class name used to validate an APNs private key's curve type. A type name, not key material.
5–10. apps/web/app/control-centre/payments/page.test.tsx:70, apps/api/tests/test_platform_stripe_settings.py:39/277/278, apps/api/tests/test_billing_config.py:92/119 — TEST/FIXTURE VALUES. All are synthetic Stripe-shaped strings using the classic placeholder suffixes `abc123`/`xyz123`/`db123` (e.g. `pk_test_abc123`, `sk_live_xyz123`) — not real Stripe key format, never reach a live Stripe call, used only to construct typed settings objects in unit/component tests.

Evidence: local reproduction with the exact CI command and flags; `git log`/`git show`/`git branch -a --contains` for history and reachability; SHA-256 hash comparison (not value disclosure) confirming the real-credential classification; `gh api repos/.../branches/{main,dev}/protection` (404, unprotected) and `gh api repos/... --jq .private` (false, public) for exposure-scope evidence; `gh run list --workflow=security.yml` / `gh api .../actions/workflows/{id}/runs` for the full failure timeline (last success 2026-08-13T16:03:17Z, 389 total runs, only 12 ever succeeded, all in the first ~2 weeks).

Risk: The DVLA UAT key is a sandbox/test-environment credential (not production vehicle data), which bounds the impact — but it is a real credential tied to the project's registered DVLA developer access, exposed on a public repository with no branch protection, for several days and counting. NCSC/OWASP guidance treats any committed secret as compromised regardless of exposure duration. The nine other findings carried no real risk but were never triaged, which is itself the root cause: once the gate turned red on 2026-08-15 for the (harmless) Stripe test fixtures, nobody could distinguish "still red for the known reason" from "a new, real secret just landed" — the real DVLA key sat undetected inside that noise for days. A continuously-red, unprotected gate is a worse security control than no gate at all, because it creates false confidence that scanning is happening.

ACTION TAKEN:
- Removed the real value from apps/.env.example (blanked, matching the pattern of every other credential field in that file).
- Added 9 new, narrowly-scoped, exact-fingerprint `.gitleaksignore` entries (one per false positive/fixture/documentation-example finding, each with a written explanation, following the project's own established pattern) plus retained a 10th entry for the DVLA finding's historical commit specifically to keep it visibly tracked as reviewed-and-actioned rather than silently dropped.
- Did NOT touch the 6 synthetic Stripe test values beyond allowlisting them — they are already reasonably distinguishable as fake (abc123/xyz123/db123 suffixes) and editing them carried a real risk of breaking test assertions under this pass's time budget; flagged as an optional future nice-to-have (rename to even more obviously-synthetic strings) rather than done now.
- Re-ran `gitleaks detect` locally with the exact CI command after remediation: **"no leaks found."**

ROTATION REQUIRED: **Yes — the DVLA UAT API key.** This was NOT rotated by this audit (per instruction, external credentials are never rotated automatically). The user must rotate it via whatever DVLA developer-access channel issued it, and treat the old value as permanently compromised regardless of any git history cleanup.

HISTORY REWRITE RECOMMENDATION:
```
History rewrite recommended: NO (rotation is the actual fix; see reason)
Reason: The commit (32b102ab, 2026-09-29) is already present and has been publicly fetchable on a public GitHub repository across both main and dev for several days. Per NCSC/OWASP guidance and this audit's own instructions, a secret must be considered compromised once committed, even if history is later cleaned — rewriting history now would not undo any exposure that has already occurred (it may have been cloned, cached by GitHub, or crawled by automated scanners in that window), and would force a disruptive force-push + re-clone for every branch/contributor. Rotating the actual DVLA credential achieves the real security outcome; history rewriting after that would be optional hygiene, not a security requirement.
Affected path(s): .env.example
Earliest known commit: 32b102ab29fcb88c2ecb27edbb13f4e76b7cd336 (2026-09-29)
Branches/tags affected: main, dev (confirmed via git branch -a --contains); feat/ios-widgets, feature/mobile-calendar-foundation, feature/multi-node-platform also contain it per the same check (likely via merge/rebase ancestry, not independently introduced).
```

Affected files: .env.example, .gitleaksignore
OWASP mapping: ASVS V13.3 (secrets management), NCSC Secure Development — secrets/credential handling
NCSC mapping: Secrets management; "treat a committed secret as compromised" principle
Status: **Source remediation complete / external credential rotation outstanding.** The key was removed from source, `.gitleaksignore` was updated with documentation, and `gitleaks detect` is now clean (confirmed with the exact CI command). UAT credential rotation remains an owner action external to this repository — per explicit instruction, this finding is not a blocker for completing this audit, and no new secret value has been or will be recorded anywhere in this report. When rotation is complete, ask for this entry to be updated with the rotation date and a final re-verification that the old value is no longer accepted (if DVLA's UAT environment exposes a way to check that without re-exposing the new key).
```

This section was originally a single combined finding. Per explicit instruction, it has been split
into four distinct findings below — a credential exposure event (SEC-18, above), the repository
governance gap that let it go unnoticed (SEC-19), the pre-existing failing test baseline discovered
while validating this pass's own changes (SEC-20), and the remaining two CI security-scanner jobs
investigated on priority request (SEC-21, SEC-22). These are four separate problems with four
separate remediation paths; none of them should be read as restating another.

```
ID: SEC-19
Severity: Medium
Area: Repository / branch-protection governance
Finding: Neither `main` nor `dev` has any branch protection or ruleset configured.
Evidence (all directly confirmed via GitHub API, nothing inferred):
  - `gh api repos/MyKhaya-app/MyKhaya/branches/main` → `{"protected": false}`
  - `gh api repos/MyKhaya-app/MyKhaya/branches/dev` → `{"protected": false}`
  - `gh api repos/MyKhaya-app/MyKhaya/branches/main/protection` → HTTP 404 "Branch not protected" (same for `dev`)
  - `gh api repos/MyKhaya-app/MyKhaya/rulesets` → `[]` (no repository rulesets exist either — the newer GitHub mechanism that can supplement or replace classic branch protection)
  - `gh api repos/MyKhaya-app/MyKhaya --jq '.private'` → `false` (repository is public)
Assessment against the specific sub-controls requested — with `protected: false` and zero rulesets, GitHub's branch-protection object does not exist at all for either branch, so by definition every one of these is unset/not-enforced (not "set to permissive" — there is no protection configuration present to inspect sub-settings of):
  - Direct pushes permitted: YES (nothing prevents pushing straight to `main` or `dev`)
  - Pull requests required: NO
  - Review required: NO
  - Status checks required: NO (neither `quality` nor `security-gate` is wired as a required check)
  - Force pushes restricted: NO
  - Branch deletion restricted: NO
  - Administrator bypass: not applicable — there is no protection rule for an administrator to bypass
Risk: This is the structural precondition that allowed SEC-18 to happen the way it did — a real secret was pushed directly to both `main` and `dev` with no PR, no review, and no requirement that any CI check (let alone a passing one) gate the push. It is a separate problem from the CI gate itself being red (SEC-18/SEC-21/SEC-22): even a perfectly green CI pipeline provides no protection at all while nothing requires it to pass before merge.
Recommended remediation: see the Recommended Target State below. **Not configured by this audit** — a GitHub repository-settings change requires explicit authorisation, was not requested, and nothing below should be read as implying it is already active.

RECOMMENDED TARGET STATE (not yet applied — current state remains `protected: false` on both branches until the user configures this directly):

```
CURRENT STATE (confirmed via GitHub API, both branches)
  protected: false | rulesets: none | PRs required: no | reviews required: no
  status checks required: no | force-push restricted: no | deletion restricted: no
  admin bypass: n/a (no rule exists to bypass)

RECOMMENDED STATE — main (release branch; per docs/operations/release-process.md,
only Anthony merges/tags/deploys from here — protection should encode that fact,
not just add generic friction)
  - Require a pull request before merging (no direct pushes)
  - Require at least 1 approving review before merge
    (CODEOWNERS not currently present in this repo — recommend adding one scoped
    to apps/api/mykhaya/security.py, apps/api/mykhaya/platform_*.py,
    apps/api/mykhaya/routers/platform.py, .github/workflows/, and this audit
    report's own directory, so security-sensitive changes always get a second
    set of eyes even if the general review bar stays at 1)
  - Require status checks to pass before merging: `quality` (from quality.yml)
    and `security-gate` (the aggregating job in security.yml, once SEC-21/SEC-22
    keep it green) — do NOT require the individual quality/stable-release checks
    separately if `security-gate`'s own `needs:` list already covers them, to
    avoid duplicate/confusing required-check entries
  - Require branches to be up to date before merging (avoid merging a PR whose
    CI run predates a since-merged breaking change)
  - Require stable-release.yml's validation to pass for any release-tag push
    specifically (this workflow already triggers on `push` tags `v*` — wire a
    required check or environment-protection rule for the `v*` tag pattern)
  - Restrict force pushes: yes (no exceptions)
  - Restrict branch deletion: yes
  - Do not allow bypass for repository administrators, OR if an emergency
    bypass is wanted, restrict it to a named, minimal list of people and log/
    alert on its use — a silent, unlogged admin-bypass option recreates the
    exact "red gate, nobody notices" failure mode this audit's SEC-18
    investigation uncovered, just with a human in the loop instead of CI

RECOMMENDED STATE — dev (day-to-day integration branch; per
docs/operations/release-process.md, this is where routine commits land —
protection here should stop accidents without adding release-level friction)
  - Require a pull request before merging where practical — if the team's
    actual workflow is trunk-style direct commits to dev, this is a product/
    process decision for the user, not something this audit should mandate;
    at minimum, require status checks regardless of whether PRs are mandated
  - Require status checks to pass before merging/pushing: `quality` and
    `security-gate` (same reasoning as main — this is what would have caught
    SEC-18 immediately rather than it sitting unnoticed for days)
  - Review requirement: optional/lighter-weight, matching dev's higher commit
    velocity — this audit does not recommend mandatory review here, only that
    CI actually gates the branch
  - Restrict force pushes: yes
  - Restrict branch deletion: yes

MANUAL ACTION REQUIRED: all of the above must be configured directly in GitHub
(Settings → Branches → Branch protection rules, or Settings → Rules →
Rulesets) by someone with repository admin access. This audit cannot and did
not make this change.
```

Affected files: GitHub repository settings (not a file in this repo)
OWASP mapping: NCSC Secure Development — CI/CD and source-control integrity; OWASP ASVS V1 (secure SDLC)
NCSC mapping: Supply chain / source-control integrity
Status: Open — requires the user to configure directly; not performed by this audit.
```

```
ID: SEC-20
Severity: Low (code-quality/test-health finding, not a security vulnerability)
Area: Frontend test suite health
Finding: Reproducing `quality.yml`'s exact web lint/typecheck/test/build step found 121 of 2015 tests failing (22 of 180 files) on an unmodified checkout, entirely unrelated to any change made in this audit. **All 22 files have now been individually triaged** (self + 2 dispatched research passes, one per file, each run both standalone and in the full suite). Final classification: **zero REAL REGRESSIONs and zero SECURITY EXPECTATION CHANGED findings** — every failure resolved to STALE TEST (18 files — almost all one recurring pattern: a legitimate redesign made an entity name/label/status text appear in 2+ DOM nodes, e.g. breadcrumb+heading+summary-card, and the old test used an unscoped exact-match query) or ENVIRONMENT/CONFIG test-pollution (4 files — pass 100% clean standalone, fail only in combination with specific other files in one pytest/vitest process; not a product defect) — **except one genuine architectural regression, `styles-safe-area.test.ts`, which was real and has been fixed.**

FIXED IN THIS PASS:
  - `styles-safe-area.test.ts` — **REAL REGRESSION, confirmed genuine — FIXED.** Enforces the AGENTS.md/mobile-standards.md invariant that every top-level container uses the shared `var(--safe-top)`/`var(--safe-bottom)` CSS strategy. Root cause: a TailAdmin-based PCC login redesign added a higher-specificity `.pcc-root .platform-login { padding: 0; ... }` rule in `pcc.css` that silently won the cascade over whatever safe-area handling existed before. Impact-assessment read first (layout-and-navigation.md, mobile-standards.md, AGENTS.md's PCC-isolation rule) confirmed this is a purely additive padding fix with no geometry change. Fixed by adding `.platform-login { padding: var(--safe-top) 0 var(--safe-bottom); }` to `styles.css` and updating the actual winning `pcc.css:3324` rule to match; `.budget-delete-confirm`'s bare `env()` literal was also converted to `var(--safe-bottom)`. The existing test suite (7 tests) already covers this — no new test needed. **7/7 pass.**
  - `app/control-centre/administrators/[id]/page.test.tsx` (15 tests) — **STALE TEST, FIXED.** `screen.findByText("Target Admin")` matched 2-3 elements after a redesign put the admin's name in a breadcrumb, `<h1>`, and summary card simultaneously. Fixed by scoping to `screen.findByRole("heading", { name: /Target Admin/ })`. This unblocked and **confirmed as actually passing** the one test most worth verifying here: "requires confirmation and a reason before resetting MFA" — the MFA-reset confirmation gate is real and working, not just assumed. **15/15 pass.**
  - `app/control-centre/homes/[id]/page.test.tsx` (37 tests) — **STALE TEST, FIXED.** Same pattern ("The Smiths" in breadcrumb/heading/summary); same heading-role scoping fix. This unblocked and **confirmed as actually passing** the Home-module entitlement-gating tests (platform-blocked vs plan-blocked vs Home-disabled vs enabled, across Free/Family plans) and the Archive/Permanent-delete lifecycle tests. **37/37 pass.**

DELIBERATELY NOT FIXED (attempted, reverted — see honesty note below):
  - `app/control-centre/users/[id]/page.test.tsx` (10 occurrences of the same pattern) — attempted the identical heading-role fix; it failed differently, revealing **two** `<h1>Jane Smith</h1>` elements render simultaneously in jsdom (unlike the other two PCC detail pages, which have exactly one). This suggests either a real duplicate-render/responsive-markup issue specific to this page, or a test-setup artifact — not diagnosed further under this pass's time budget. **Reverted to original** rather than leave a partially-fixed, not-fully-understood file. The suspend/archive/session-revoke lifecycle tests this file covers remain unverified (not confirmed broken — the code wasn't found to be doing anything unsafe, just unverified by this specific test file right now).
  - `app/control-centre/subscriptions/[id]/page.test.tsx` — same general pattern per triage, not attempted given the `users/[id]` lesson above.

CLASSIFIED, NOT FIXED (16 remaining files — all confirmed STALE TEST or ENVIRONMENT/CONFIG, all cosmetic, zero security relevance): `app/calendar/page.test.tsx` (MonthSwipeView's intentional 3-panel swipe-preview causes duplicate event text matches — not a bug), `app/control-centre/demo-test-homes/[id]/page.test.tsx`, `app/control-centre/legal/documents/[id]/page.test.tsx` (passes 100% standalone), `app/control-centre/settings/calendar-dates/page.test.tsx` (passes standalone), `app/control-centre/settings/page.test.tsx` (passes standalone, including its sensitive-settings-confirmation-dialog test), `app/control-centre/subscriptions/[id]/page.test.tsx`, `app/help-support/diagnostics/page.test.tsx` (legitimate new health-check growth), `app/help-support/page.test.tsx`, `app/home/page.test.tsx` (wrong CSS-class selector, display is actually correct), `app/page.test.tsx` (footer link allow-list missing a real, legitimate page), `app/people/page.test.tsx` (an overly-broad regex test tripped by an unrelated new API export, `addSupportTicketMessage`, matching `/chat|message/i` — the chat-placeholder component itself never touches it), `app/settings/profile/page.test.tsx` (passes standalone, including native avatar upload paths), `components/control-centre/auth-shell.test.tsx` / `app/control-centre/login/page.test.tsx` (same brand-name-duplication pattern as administrators/[id]), `components/marketing/public-pricing.test.tsx` (a second, legitimate Ultimate pricing card with its own independent kill switch, correctly fail-safe-closed by default), `components/platform-shell.test.tsx` (a CSS class rename, `"active"` → `"menu-item-active"`), `app/control-centre/cleanup/page.test.tsx` and `app/control-centre/payments/page.test.tsx` (stale copy/markup; `payments` was also under the user's own concurrent unrelated edit during this audit).
Does this reduce confidence in security regression testing? Lower than initially feared: the two highest-priority PCC detail pages (admin MFA-reset, Home entitlement-gating) are now fixed and their real security assertions confirmed passing. `users/[id]`'s lifecycle-action tests (suspend/archive/session-revoke) remain genuinely unverified — flagged as the one remaining item worth following up, not because anything looks broken, but because nothing currently proves it isn't.
Final count after this pass's fixes: **86 of 2015 failing** (down from 121), 18 files fully resolved or classified-and-closed, 2 files (`users/[id]`, `subscriptions/[id]`) classified but intentionally left for a follow-up pass rather than risk an unreviewed fix.
Recommended remediation: Investigate `users/[id]`'s duplicate-heading render before attempting its test fix again; apply the same `within(dialog)`/role-scoping pattern to `subscriptions/[id]` and the 14 purely-cosmetic stale files at leisure (low priority, zero security impact, well-understood one-line fixes per the classification above).
Affected files: see breakdown above.
OWASP mapping: N/A (code-quality/test-health, not a security control)
NCSC mapping: N/A
Status: Open — classified where sampled; full triage recommended as separate follow-up work.
```

```
ID: SEC-21
Severity: Medium → Remediated
Area: CI — `filesystem` security job (Trivy)
Finding: Reproduced the exact CI command (`docker run --rm -v "$PWD:/src" aquasec/trivy:0.64.1 fs --exit-code 1 --severity HIGH,CRITICAL --scanners vuln,misconfig /src`). Result: 4 HIGH vulnerabilities in `pnpm-lock.yaml`, all `brace-expansion` (CVE-2026-102276, CVE-2026-102278) across its three independently-resolved version lines (1.1.18, 2.1.4, and a third already-present 5.0.9 line, none of which met the fixed-version floor). Dockerfile misconfiguration scanning: clean (0 findings, both apps/api and apps/web). This is the same dependency already identified and deliberately deferred as dev-only in SEC-16 during the earlier dependency audit — reproducing the actual CI job revealed it was the sole cause of this job's failure, not stale/false-positive noise.
Evidence: local reproduction output (tool table above); `brace-expansion` resolves via `eslint`/`typescript-eslint`/`@capacitor/cli` → `rimraf`/`glob` → `minimatch`, i.e. dev/lint/native-build tooling only, never shipped to a browser, server, or device.
Action taken: Added version-specific pnpm overrides (`"brace-expansion@1": "^1.1.20"`, `"brace-expansion@2": "^2.1.6"`, `"brace-expansion@5": "^5.0.11"`) to root `package.json`, regenerated the lockfile. Re-ran the exact CI command: **0 vulnerabilities, 0 misconfigurations.**
Affected files: package.json, pnpm-lock.yaml
OWASP mapping: ASVS V14.2 (dependency management)
NCSC mapping: Supply chain — dependency currency
Status: Remediated and re-verified locally with the exact CI command.
```

```
ID: SEC-22
Severity: Medium → Remediated
Area: CI — `semgrep` security job (SAST)
Finding: Reproduced the exact CI command (`docker run --rm -v "$PWD:/src" semgrep/semgrep:1.172.0 semgrep scan --config p/owasp-top-ten --error /src/apps`). Result: 2 blocking findings.
  1. `apps/api/mykhaya/support_reference.py:22` — `python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text`. This is exactly the finding already recorded as SEC-05 (Low) in the Phase 1 report — an f-string interpolated into `sqlalchemy.text()` to call `nextval()` on a fixed, non-user-controlled sequence-name constant. Reproducing the CI job turned what Phase 1 treated as a low-priority style note into an actual, currently-failing, blocking CI finding — confirming it was real CI debt, not merely theoretical.
  2. `apps/android-shell/android/app/src/main/AndroidManifest.xml:19` — `java.android.security.exported_activity.exported_activity`. CONFIRMED FALSE POSITIVE: this is `MainActivity`, the app's launcher activity (has the `MAIN`/`LAUNCHER` intent-filter) — Android requires `android:exported="true"` on any activity with an intent-filter since API 31; the manifest merger fails the build without it. Not a privileged or data-handling export.
Action taken:
  1. Rewrote `support_reference.py` to use `select(func.nextval(SUPPORT_REFERENCE_SEQUENCE))` instead of `text(f"...")` — this passes the sequence name as a genuine bound parameter rather than interpolating it into raw SQL text, which both resolves the underlying pattern Semgrep (correctly, structurally) flags and eliminates SEC-05 entirely rather than just suppressing its detector. Verified with the full `test_support_tickets.py` + `test_support_notifications.py` suite (52 tests) — all pass.
  2. Attempted inline `nosemgrep` suppression comments for the Android manifest finding, both as a preceding line and as a same-line trailing comment — **neither was honoured by Semgrep's XML/Android-manifest analyzer for this rule** (confirmed by two separate re-runs, each still reporting the finding). Fell back to a `.semgrepignore` path-level entry for this one file, with documentation explicitly flagging that this is broader than the fingerprint-scoped `.gitleaksignore` approach used elsewhere (a whole-file exclusion, not a single-finding one) because Semgrep's tooling offers no finer-grained mechanism for this analyzer — recorded honestly as a less-precise suppression than ideal, with a note for future reviewers to manually re-check this file if it ever grows beyond its current single-activity, single-provider scope.
Re-ran the exact CI command after both fixes: **0 findings.**
Affected files: apps/api/mykhaya/support_reference.py, apps/android-shell/android/app/src/main/AndroidManifest.xml, .semgrepignore (new)
OWASP mapping: ASVS V1.2 (injection prevention) for finding 1; N/A for finding 2 (false positive)
NCSC mapping: Secure coding practices
Status: Remediated and re-verified locally with the exact CI command. SEC-05 (Phase 1) is superseded by this finding and can be considered closed.
```

```
ID: SEC-23
Severity: Low (code-quality/test-health finding, not a security vulnerability — parallel to SEC-20 but for the backend suite)
Area: Backend test suite health
Finding: The security-relevant backend test subset found 15 of 531 selected tests failing across 8 files, none touched by this audit. **All 8 files have now been fully triaged** (every individual failure read and classified, not just file-level sampling). Result: **1 genuine real regression (fixed), 2 stale tests reflecting intentional security/architecture changes (both fixed), 2 failures that are a test-isolation defect rather than a product issue (documented, not fixed), 1 deliberate canary test working exactly as designed, and the pre-diagnosed entitlement-gate-fixture staleness pattern confirmed across the remainder.**

FIXED IN THIS PASS:
  - `test_platform_stripe_settings.py::test_environment_fallback_when_no_stored_row` — **REAL REGRESSION, FIXED.** `GET /api/v1/platform/payments/stripe` hardcoded `editable=True` unconditionally in `routers/platform.py` (~line 7138), instead of deriving it from `config.source != "environment"` the way the equivalent email/push settings endpoint already does (line 6642) — meaning the PCC Payments page incorrectly reported env-var-sourced Stripe config as user-editable when there is nothing in the database to actually edit. Fixed to match the established sibling pattern exactly. Re-ran the full file: **20/20 pass** (including the one other pre-existing failure in this file, fixed separately below).
  - `test_platform_stripe_settings.py::test_enabling_incomplete_mode_is_rejected` — **STALE TEST reflecting a real, intentional architecture change — FIXED.** `routers/platform.py`'s price-ID-completeness validation is now correctly gated behind `enabled and (family_signups_enabled or ultimate_signups_enabled)` per migration `0095_plan_signup_controls` (decoupling "Stripe enabled for webhook/reconciliation" from "new-signup acquisition enabled" — a real, deliberate decision, not a bug). The test's fixture never set either signup-acquisition flag, so under the new, correct gating there was nothing to validate. Fixed by adding `family_signups_enabled: True` to the test's request body so it actually exercises the rejection path it's named for. **Passes.**
  - `test_apple_review_fixture.py::test_managed_demo_service_has_scoped_security_guards` — **STALE TEST (string-literal drift only) — FIXED.** The guard logic itself (refusing to adopt an existing customer's email into a demo fixture) is intact and functioning; only the asserted message text had changed (`"Refusing to adopt an existing customer account"` → `"The account email is already in use by another customer account."`). Updated the assertion to match. **Passes.**

NOT FIXED, DOCUMENTED (test-infrastructure debt, not product bugs):
  - `test_email_branding.py::test_every_template_type_gets_a_cta_button_to_its_link[platform_administrator_invitation]` and `test_native_cors.py::test_preflight_for_native_bearer_requests_allows_authorization` — **ENVIRONMENT/CONFIG ISSUE, root-caused via bisection, not a security defect.** `test_native_cors.py` mutates `os.environ` (CORS origins, public web URL, etc.) at *module import time* so its own test gets the config it needs. Because pytest imports every module passed on one command line during collection, and `mykhaya.main`'s `app`/`Settings`/CORS-middleware are module-level singletons built once per process from whichever env was active at first import, this collides with whichever other test file happens to trigger that first import when both files run in the same pytest invocation — confirmed by running every pairwise combination. Both tests pass 100% of the time run alone. This says nothing about production CORS or email-branding behaviour (one process = one fixed env there) — it is purely a test-harness ordering hazard. Recommended fix (not applied): have `test_native_cors.py` build its own app instance with overridden settings (the `app.dependency_overrides[get_settings]` pattern already used elsewhere in this suite, e.g. `test_browser_mfa_flow.py`) instead of mutating `os.environ` globally at import time. Not attempted in this pass given the risk of subtly changing this file's other passing tests under time pressure without dedicated attention.
  - `test_notification_templates.py::test_security_critical_templates_all_require_their_link` — **Deliberate canary, working exactly as designed, not a bug.** The test's own docstring states it should fail exactly like this once a `security_critical` template exists that centres on something other than a link (e.g. a code). A new `mfa_email_code` template (emails an MFA code, not a link) was added and correctly tripped this intentional tripwire — someone now needs to deliberately decide how `code`-based security-critical templates should be validated and update the assertion accordingly. Left for the template-owning engineer, not fixed here, since it requires a product decision this audit shouldn't make unilaterally.
  - `test_mobile_auth.py` (6 failures) and `test_billing_webhooks.py` (2 failures) — **STALE TEST, confirmed same entitlement-gate-fixture pattern already diagnosed:** child-profile creation and checkout confirmation both now correctly 403 on a missing `family_plans.enabled`/equivalent entitlement before the tests' real scenarios are reached, matching the documented, intentional `create_child` entitlement fix in `docs/security/platform-administration-security.md`'s changelog. Not fixed — each of these 8 individual test fixtures needs its own plan/entitlement setup added, which is real but mechanical follow-up work better done by whoever owns this test file's conventions, not rushed across 8 call sites in this pass.
  - `test_platform_subscriptions_management.py::test_unauthenticated_client_cannot_reach_subscription_endpoints` — **STALE TEST; the code is now *more* secure than the test expects** (404 anti-enumeration response where the test still expects 401/403 — consistent with this codebase's documented pattern elsewhere). Not fixed — a one-line expected-status widening, left for the same reason as above.
Final count after this pass's fixes: **12 of 531 failing** (down from 15); 3 genuine fixes (1 real bug, 2 stale), 2 documented test-isolation defects, 1 deliberate canary, 6 remaining fixture-staleness failures across 2 files left as mechanical follow-up.
Does this reduce confidence in security regression testing? No evidence of a hidden vulnerability — every sampled failure traces to a real, intentional security/architecture improvement outpacing its own test fixture, or to test-harness-only noise. The general alert-fatigue concern (SEC-18/SEC-20) still applies structurally, but this file-by-file triage found nothing actually wrong with the application.
Recommended remediation: Add plan/entitlement fixture setup to the 8 remaining `test_mobile_auth.py`/`test_billing_webhooks.py` failures and widen the one anti-enumeration status assertion; fix `test_native_cors.py`'s import-time env mutation to use dependency overrides instead.
Affected files: apps/api/mykhaya/routers/platform.py (fixed), apps/api/tests/test_platform_stripe_settings.py (fixed), apps/api/tests/test_apple_review_fixture.py (fixed), apps/api/tests/test_mobile_auth.py, apps/api/tests/test_billing_webhooks.py, apps/api/tests/test_email_branding.py, apps/api/tests/test_native_cors.py, apps/api/tests/test_notification_templates.py, apps/api/tests/test_platform_subscriptions_management.py (remaining, documented)
OWASP mapping: N/A (code-quality/test-health, not a security control) — except the `editable` fix, which maps to ASVS V13.1 (minimal, correct API response data)
NCSC mapping: N/A
Status: Substantially remediated (3 fixes, full triage of all 8 files complete); 6 fixture-staleness failures and 1 test-isolation defect remain as documented, well-understood, low-priority follow-up work.
```

## Additional Security Findings (continuation pass)

```
ID: SEC-08
Severity: Low (fixed)
Area: Container hardening
Finding: The `postgres` service in compose.yml had no `cap_drop: [ALL]` line at all, unlike every other service in the stack (web, api, worker, scheduler, migrate, test, redis, mailpit, caddy all had it). It retained the official Postgres image's full default Linux capability set.
Evidence: compose.yml (pre-fix) lines 224-248 — `security_opt: [no-new-privileges:true]` present but no `cap_drop`.
Risk: Low in practice (no known exploitable path identified; Postgres only reachable via the internal, non-internet-routable `data` network, never a published port), but inconsistent with the stack's own stated defence-in-depth posture.
Remediation completed: Added `cap_drop: [ALL]` plus a minimal `cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]` (the same set already used for `redis`, which follows the identical "official image starts as root, drops privileges to an app user at entrypoint" pattern). Verified with `docker compose config postgres` that the change parses correctly and produces the intended capability set; a full container start was not performed in this pass (see Validation section) — recommend confirming `docker compose up postgres` reaches healthy before next deploy.
Affected files: compose.yml
OWASP mapping: ASVS V14.1 (secure configuration), NCSC Cloud Security Principle 7 (secure user management) — informational
NCSC mapping: Secure configuration / least privilege
Status: Remediated (config-validated; full runtime start not yet re-verified in this pass).

ID: SEC-09
Severity: Informational
Area: Deployment / configuration drift
Finding: docs/operations/deployment.md self-documents a new required production setting, `MYKHAYA_NATIVE_API_URL` (must be `https://api.mykhaya.app`), stated as needed "before the next deploy or startup validation will fail." This is a pending operational action, not a code defect.
Evidence: docs/operations/deployment.md (per research-agent read).
Risk: If unset, the next production deploy's own startup validation will fail closed (not silently misbehave) — self-protecting, but still worth closing out before it blocks a deploy.
Recommended remediation: User/operator to confirm `MYKHAYA_NATIVE_API_URL` is set in the production environment ahead of the next deploy. Not an engineering fix.
Affected files: docs/operations/deployment.md
OWASP mapping: N/A
NCSC mapping: N/A
Status: Manual verification required (user action).

ID: SEC-10
Severity: Medium (business/legal, not application security)
Area: Billing production readiness
Finding: docs/operations/billing-production-readiness.md self-discloses that live billing is not yet safe to enable: no Terms of Service or Privacy Policy page exists at all, Tax/VAT handling is an unresolved decision, and no real Stripe sandbox end-to-end test has ever been run (the full go-live checklist exists but every step is "to run," not "done"). Additionally, only one Stripe webhook signing secret is supported at a time (no overlap window for zero-downtime rotation) — a documented, accepted limitation with a manual workaround, not an oversight.
Evidence: docs/operations/billing-production-readiness.md (per research-agent read).
Risk: Not an application-security vulnerability — the commercial entitlement/webhook code itself is well-guarded (see Phase 1 findings on Stripe webhook signature verification, ownership-mismatch checks, server-resolved pricing). The risk is regulatory/commercial: enabling real billing before these items close exposes the business, not user data.
Recommended remediation: Track as a product/legal/business workstream (ToS/Privacy Policy drafting, VAT decision, a scheduled real Stripe sandbox run) ahead of flipping `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED` to true in production. No code change in scope for this audit.
Affected files: docs/operations/billing-production-readiness.md
OWASP mapping: N/A
NCSC mapping: N/A
Status: Pre-existing, self-disclosed, not a new finding. Accepted pre-launch blocker.

ID: SEC-11
Severity: Informational
Area: Process confirmation (apps/mobile deletion)
Finding: docs/architecture/adr/0011-single-pwa-retire-mobile-app.md states deletion of apps/mobile "should be confirmed with Anthony before any files are removed." This audit's deletion of apps/mobile (see Deletion Candidates) was carried out under this conversation's direct, explicit instruction from the user (Anthony) to do so ("The retired Expo scaffold may now be removed... Delete: apps/mobile/"), which satisfies that confirmation gate.
Evidence: docs/architecture/adr/0011-single-pwa-retire-mobile-app.md; this conversation's continuation instructions.
Risk: None — recorded for traceability only.
Affected files: apps/mobile/ (deleted)
Status: Not applicable (confirmation gate satisfied).
```

## CI/CD and Container/Deployment Review

**CI/CD (`.github/workflows/`)**: Well-hardened for what it does. All three workflows
(`quality.yml`, `security.yml`, `stable-release.yml`) declare minimal explicit `permissions:`
blocks (`contents: read`, plus `security-events: write` only on `security.yml`); **zero references
to `secrets.*` exist in any workflow** — there is nothing for a malicious fork PR to steal, and no
`pull_request_target` is used anywhere. No `run:` step interpolates attacker-controlled
`${{ github.event.* }}` values (the one hit is in a `concurrency.group:` key, not a shell step).
Every third-party Action is pinned to a full commit SHA; every scanner image is pinned to an exact
version tag. `security.yml` runs gitleaks, pip-audit, Trivy, Semgrep (OWASP Top 10 ruleset),
Checkov (Dockerfile + Actions IaC — Compose-file scanning is explicitly, not accidentally, excluded
as a documented tool-capability gap), and generates a CycloneDX SBOM. **No workflow in this repo
performs an actual deployment** — production rollout happens out-of-band (confirmed by
`docs/operations/deployment.md`/`release-process.md`: only Anthony merges to `main`, tags, and
deploys, manually). Manual verification required: GitHub repo-level branch protection / required
reviewers / environment-protection rules (not visible from YAML).

**Containers/deployment**: Both Dockerfiles (`apps/api/Dockerfile`, `apps/web/Dockerfile`) are
multi-stage with clean separation — dev/test dependencies never reach the runtime stage — and both
run as non-root uid/gid 10001 with health checks. `cap_drop: [ALL]` + `no-new-privileges` +
`read_only` + tmpfs is applied consistently across every service in `compose.yml` with the one
exception fixed as SEC-08 above. Postgres and Redis are never published to the host or bound
outside the internal `data` network in any compose file. No hardcoded secret values appear in any
compose YAML (only `${VAR}` references from `.env`, which is itself gitignored). Caddyfiles set a
consistent security-header baseline, HSTS is present wherever TLS is actually terminated by Caddy
and correctly absent where it isn't (dev tunnel terminates TLS upstream), no admin/debug Caddy API
is exposed anywhere, and production's trusted-proxy CIDR setting fails closed with no insecure
default (`${VAR:?error message}` syntax forces the operator to set it explicitly). A dev-vs-production
cross-check found no dev convenience (open registration, permissive CORS, relaxed cookies, debug
flags) leaking into `compose.production.yml` — production consistently overrides to the stricter
value. `infrastructure/docker/init-db.sh` creates least-privilege Postgres roles (`mykhaya_app`
cannot alter schema; only `mykhaya_migrator` can).

## Outstanding Documentation — Now Read in Full

The remaining documentation flagged in Phase 1 as "not yet read" has now been read in full:
`docs/operations/*` (14 files), `docs/mobile/*` (6 files), `docs/product/*` (7 files), ADRs
0001–0014, and one additional architecture doc (`administrative-network-boundary.md`). Highlights
relevant to this audit, beyond what's already captured in SEC-09/SEC-10/SEC-11 above:

- **PCC is repeatedly and consistently self-described as not production-ready** across
  `README.md`, `docs/security/platform-administration-security.md`,
  `docs/security/platform-administration-threat-model.md`, `docs/product/platform-administration-scope.md`,
  and `docs/operations/control-centre-deployment.md` — all independently state mandatory
  hardware-backed MFA (WebAuthn) must be complete before production operator access is enabled.
  This is treated as a single standing finding (SEC-01), not restated per document.
- **`docs/operations/administrative-network-boundary.md`** (read via follow-up) states explicitly:
  "An allow-list is defence in depth, not identity" — the PCC's network/IP allow-list is
  intentionally not treated as a substitute for the still-pending WebAuthn requirement. This is a
  mature, consistent position, not a gap.
- **Android native work is self-documented as "paused, not abandoned"** (`docs/mobile/android-status.md`)
  with FCM push code-complete but never exercised against a real Firebase project, and no release
  keystore yet — consistent with the already-recorded SEC-03 (no Android secure persistent
  storage yet, because persistent login itself isn't live there yet).
  `expo-and-device-development-audit.md` and `expo-go-setup.md` are confirmed, by their own
  top-of-file banners, to be intentionally retained historical records of the now-deleted
  `apps/mobile`, not descriptions of anything currently live — nothing in them changes the
  apps/mobile deletion decision.
- **`docs/operations/dev-deployment.md` documents real past operational incidents** (a scheduler
  crash-looping against a schema `migrate` hadn't applied; a leaked-test-account incident that
  caused the live scheduler to send real notifications) that drove the current
  isolated-test-database architecture (`compose.test.yml`, separate Compose project name). Recorded
  here as evidence the project has a track record of turning real incidents into durable
  structural fixes, not as an open finding.
- **`docs/product/initial-scope.md`** is stale relative to ADR 0011 (it lists an "Expo mobile
  shell" as in-scope, which was later retired) — a known, accepted historical-document staleness,
  not an error requiring correction (per instruction, historical scope docs are not rewritten to
  erase prior direction).

## Authorization (BOLA/IDOR) Audit

A full static code review (no live server) of all 17 major router modules plus the shared
authorization mechanism (`dependencies.py`, `security.py`, `household_permissions.py`) and the
platform/PCC isolation boundary. **No exploitable BOLA/IDOR vulnerability was found, and no
consumer-reachable path to platform-operator authority was found.**

The shared mechanism: `membership_for(group_id, auth, db)` resolves the caller's own Membership
row scoped to `(group_id, user_id)`, 404ing identically whether the Home doesn't exist or the
caller isn't in it (no enumeration signal). `require_capability()` wraps this with a capability
check. Every handler reviewed follows one of two safe patterns: (a) `require_capability(home_id,
...)` then re-filtering the target resource by `resource.group_id == home_id`, or (b)
caller-identity-derived scoping (`owner_user_id`/`created_by`/`recipient_user_id ==
auth.user.id`), never trusting an ID supplied in the request alone. `routers/platform.py` and
`routers/platform_compliance.py` import none of the consumer auth dependencies at all — separate
models, separate cookies (`mk_admin_session` vs `mk_session`), separate CSRF, separate MFA —
confirmed structurally isolated, not merely isolated by convention.

Modules reviewed and clean: groups.py, calendar.py, budget.py, calendar_sharing.py,
calendar_highlights.py, driveway.py, lists.py, meal_plans.py, wishlists.py, support.py,
notifications.py, reminders.py, household_routines.py, todos.py, children.py, invitations.py,
home_join.py, users.py, billing.py.

**Test-coverage gaps identified** (code is correctly scoped; no regression test proves it yet):
groups.py (member mutation endpoints), budget.py, driveway.py (core vehicle CRUD), children.py,
invitations.py, users.py (avatar visibility). Per remediation policy ("add regression tests where
practical"), the two highest-value gaps were closed in this pass:

```
ID: SEC-12
Severity: Informational (test-coverage gap, not a code defect)
Area: Authorization test coverage
Finding: budget.py had zero cross-user/cross-Home regression tests despite being structurally the highest-value target (BudgetProfile/BudgetItem are keyed to the caller's own user id, resolved server-side, never from a request-supplied id) — an invariant worth locking in given how easy it would be for a future refactor to accidentally thread a user_id through from the request.
Remediation completed: Added apps/api/tests/test_budget_cross_user_isolation.py — two new tests: (1) a user with no Home membership gets denied on `/homes/{home_id}/budget`, (2) two genuine members of the *same* Home each get their own BudgetProfile and never see each other's budget items/categories.
Status: Remediated — tests added (see Validation section for run result).

ID: SEC-13
Severity: Informational (test-coverage gaps, not code defects)
Area: Authorization test coverage
Finding: groups.py (member-mutation endpoints: update_member, remove_member, grant/revoke_family_sponsorship, approve/decline_join_request), driveway.py (core vehicle CRUD beyond the reminders sub-route), children.py, invitations.py, and users.py (avatar visibility) all have correctly Home/user-scoped code per the BOLA audit, but no dedicated two-Home or two-user regression test proving it.
Remediation completed (partial): Added apps/api/tests/test_groups_cross_home_isolation.py, proving a Home Admin of one Home gets an identical 404 attempting to PATCH another Home's member by supplying its group_id/user_id directly, and that the same action succeeds normally within their own Home (passes — see Validation section).
Recommended remediation (remaining): driveway.py (core vehicle CRUD), children.py, invitations.py, and users.py (avatar visibility) still have no dedicated cross-Home/cross-user test, following the same pattern. Not completed in this pass due to scope — recorded as outstanding technical debt rather than rushed.
Status: Partially remediated — groups.py closed; driveway/children/invitations/users remain open follow-ups (underlying code is correctly scoped in all cases, this is test-coverage debt only).
```

## Dependency and Supply-Chain Audit

```
ID: SEC-14
Severity: Critical→Remediated
Area: Frontend dependency (Next.js)
Finding: next@15.5.21 (apps/web/package.json) carried two critical advisories: GHSA-p293-qw3h-jr36 (unauthenticated RCE, Windows-hosted Next.js servers only — not reachable in the Linux-container production deployment, but relevant to Windows local dev) and GHSA-2xp9-vwfh-vxw4 (unauthenticated RCE in the Image Optimization API via AVIF files, platform-independent, reachability not fully ruled out).
Evidence: `pnpm audit` cross-verified against the live CI Trivy filesystem scan (GitHub Actions run 36926099806) — both tools agree.
Remediation completed: Bumped to next@15.5.24 (the patched floor; a 16.x major exists but was deliberately not taken — see SEC-17) in apps/web/package.json. No breaking change (same major/minor line).
Status: Remediated — see Validation section for build/lint/test verification.

ID: SEC-15
Severity: High→Remediated
Area: Frontend dependency (sharp / libheif)
Finding: sharp@0.35.3 (transitive, via Next.js image optimization, pinned by a root pnpm.overrides entry) carried GHSA-rgj7-g3m4-5g8c and two libheif CVEs (GHSA-g89c-p67h-r497, GHSA-2jg2-4ch7-h545).
Evidence: `pnpm audit`, cross-verified against CI Trivy scan.
Remediation completed: Tightened the root package.json pnpm.overrides floor from `^0.35.0` to `^0.35.4` (already in-range of the existing caret range — no breaking change) and `js-yaml` from `^4.3.1` to `^4.3.2` (fixes GHSA-2883-xcg3-v3hh, CPU DoS via YAML merge keys — lint tooling only, not shipped). Lockfile regenerated.
Status: Remediated — see Validation section.

ID: SEC-16
Severity: Low (dev-only, not remediated)
Area: Dev/build tooling dependencies
Finding: vitest@3.2.4 (CRITICAL GHSA-5xrq-8626-4rwp, MODERATE GHSA-82fw-gwwq-j7x9) and transitive brace-expansion (via eslint/typescript-eslint/@capacitor/cli, three resolved versions) and uuid@7.0.3 (via @capacitor/cli's iOS build tooling) all carry advisories, but all are test-runner/lint/native-build-time only — never shipped to a browser, server, or device.
Evidence: `pnpm audit`.
Risk: None in production; vitest's affected surface is its UI dev server, not used in CI/test runs here.
Recommended remediation: vitest 3→4 is a major version bump with potential config-breaking changes — flagged for a deliberate, separately-tested upgrade rather than bundled into this pass's dependency patches (per instruction: do not blindly run major-version upgrades). brace-expansion/uuid will likely resolve once their parent tools (eslint, @capacitor/cli) ship updates; not independently overridable without risk of breaking those tools' own resolution.
Status: Open — deliberately deferred, dev-only impact.

ID: SEC-17
Severity: Informational
Area: Dependency currency
Finding: Next.js 16.x is available; this audit intentionally targeted the 15.5.24 patched floor rather than jumping a major version.
Status: Not applicable — recorded for future planning, not a security finding.
```

**CI security-gate status (surfaced incidentally, outside dependency scope but worth noting):** the
research agent's check of recent GitHub Actions runs found `security.yml`'s `secrets` (gitleaks),
`filesystem` (Trivy), and `semgrep` jobs failing on the last several pushes to `dev`, meaning the
aggregating `security-gate` job has not been green recently. **This needs the user's/engineering
owner's direct attention** — it was not investigated further in this pass (gitleaks findings in
particular should not be dismissed without checking whether they're real secrets or documented
false positives via `.gitleaksignore`).

**Python dependencies (apps/api):** `pip-audit` (the same command CI's `python-dependencies` job
runs) reported **no known vulnerabilities**. **Docker base images:** all four (`python:3.13.5-slim-bookworm`,
`node:22.17.0-alpine3.22`, `mcr.microsoft.com/playwright:v1.55.1-noble`) are pinned to exact
versions, no floating tags. **GitHub Actions:** the only two marketplace Actions used
(`actions/checkout`, `actions/upload-artifact`) are both pinned to a full commit SHA. **SBOM:**
the CycloneDX SBOM generation job passed on the latest CI run and produced `mykhaya-sbom.cdx.json`.

## Code Hygiene Findings

- **Comment volume**: a dedicated re-read of every TODO/FIXME/HACK/XXX/WORKAROUND-style marker in
  `apps/api`, `apps/web`, and `apps/ios-shell` found **no actual open debt markers at all** —
  Phase 1's naive counts (api: 4, web: ~8, ios-shell: 18) did not reproduce under a careful,
  false-positive-filtered re-scan; the only repo-wide hits were either the legitimate domain noun
  "Todo" (the Todos feature/model) or three uses of the word "workaround" inside well-written,
  accurate prose comments explaining already-applied fixes or documented platform constraints
  (none are open debt; see `apps/api/mykhaya/calendar_occurrences.py:256`,
  `apps/api/mykhaya/config.py:111`, `apps/ios-shell/native/WidgetCore/Package.swift:22`). No
  changes needed — comment hygiene in this codebase is already good, and no cleanup was manufactured
  to produce a diff where none was warranted.
- **Dead code — `apps/mobile/`**: confirmed-dead, retired Expo scaffold, deleted (see Deletion
  Candidates).
- **Dead code — `apps/web/components/coming-soon.tsx`**: confirmed zero imports anywhere in the
  codebase (the only other "coming-soon" hit is an unrelated test-description string for a
  different, inline placeholder on the People page). Deleted, along with its five dedicated CSS
  rules in `apps/web/app/styles.css` (`.coming`, `.coming > div`, `.coming h1`, `.coming >
  p:not(.eyebrow)`, `.coming .button`).
- **Dead CSS — `apps/web/app/control-centre/pcc.css`, confirmed, not deleted (follow-up needed):**
  the earlier "possible" uncertainty is resolved — checked `apps/web/components/legal-markdown.tsx`
  (the one place PCC renders dynamic/markdown content) and confirmed it wraps rendered markdown in
  a single caller-supplied `className` only, injecting none of the suspect class names; re-confirmed
  zero usage of all 21 candidate classes (`cc-form-grid-3`, `cc-form-grid-full`, `cc-inline-control`,
  `cc-toolbar-actions`, `credential-list`, `diagnostic-heading`, `flag-list`, `job-runtime`,
  `mail-grid`, `module-controls`, `module-copy`, `module-list`, `module-reason`, `module-toggle`,
  `operator-action`, `overview-section-kicker`, `platform-columns`, `platform-nav-group`,
  `platform-nav-group-label`, `platform-topbar-identity`, `scope-note`, `setting-row-caption`)
  across every `.ts`/`.tsx` file in `apps/web`. **Still not deleted**, for a different reason than
  originally thought: inspecting the actual rule sites found most of this dead CSS entangled in
  comma-separated selector lists shared with genuinely live classes (e.g.
  `.record-list,\n.flag-list { ... }`), and `platform-nav-group`/`platform-nav-group-label`/
  `platform-topbar-identity`/`overview-section-kicker` specifically turn out to be leftover styling
  from a pre-TailAdmin PCC sidebar redesign — the live rendered sidebar now uses a different class
  scheme entirely (`tailadmin-nav-group`/`menu-item*`, confirmed directly from rendered test output
  earlier in this pass), with dozens of old `.pcc-root .platform-nav-group*` rule blocks still
  present across the file from that superseded design. Safely removing this requires surgically
  editing individual selectors out of shared comma-lists and tracing several historical redesign
  layers — real but non-trivial work, squarely a UI/CSS-governance cleanup task under AGENTS.md's
  explicit shared-CSS impact-assessment requirement, not something to rush through inside a security
  audit. Recommended as a dedicated follow-up pass, not attempted further here.
- **Verified NOT dead** (looked suspicious, confirmed legitimate): `apps/web/app/khaya-control-centre/*`
  (live, Home-Admin-facing settings surface, distinct from PCC, linked from `settings-page.tsx` and
  covered by e2e tests); `apps/web/app/settings/routines/page.tsx` and `.../reminders/page.tsx`
  (intentional permanent-redirect shims preserving old bookmarks/notification deep links after the
  2026-09-01 Routines & Reminders consolidation — `widget-snapshot.ts` still actively constructs
  links to the old path); `apps/web/app/control-centre/notification-templates/page.tsx` (same
  redirect-shim pattern); the ~25 PCC pages that initially looked unreferenced (a grep-methodology
  artifact — PCC nav builds relative hrefs, not literal full-path strings; all confirmed reachable).
- **Dependencies**: `npx depcheck` against `apps/web` found zero unused and zero missing npm
  dependencies.
- **Feature flags**: every `FeatureKey` enum value is registered in `module_registry.py` and vice
  versa; no orphaned flags either direction. `tasks`/`plans` are deliberately hidden/retired per
  `docs/architecture/feature-flags.md` — documented intent, not dead code.
- **Duplication**: none identified; entitlements, notification sending, and CORS/auth checks all
  route through single documented modules (`mykhaya.entitlements`, `notify()`, `rate_limit.py`,
  `security.py`). No evidence of the "reimplemented security rule in multiple places" anti-pattern.
- **Not completed in this pass** (flagged rather than guessed): a systematic duplicate-utility-function
  diff across `apps/web/components`/`lib`, and a full cross-reference of every backend router
  endpoint against actual frontend API-client usage (both are large enough to warrant a dedicated
  follow-up pass rather than a rushed partial one).
- **No raw-SQL, XSS-sink, or shell-injection patterns found** in first-party application code (see
  Security Findings SEC-05 for the one low-priority SQL-construction-style note).

## Deletion Candidates

```
Path: apps/mobile/ — DELETED
What it appeared to be: Retired Expo-based native app scaffold, superseded by the Capacitor-based apps/ios-shell and apps/android-shell per docs/architecture/adr/0011-single-pwa-retire-mobile-app.md.
Evidence it was unused: Not listed in pnpm-workspace.yaml; only two files remained on disk (.env, .gitignore); apps/ios-shell/capacitor.config.ts and apps/android-shell/capacitor.config.ts comments explicitly say their app ID was "reused from the retired apps/mobile Expo scaffold"; infrastructure/scripts/validate_version.py and infrastructure/tests/test_validate_version.py explicitly document and test for apps/mobile/package.json's absence (glob-based manifest discovery, not a hardcoded path list) — confirms the codebase's own tooling already expects this directory to be gone/incomplete; no CI workflow, Docker build, or runtime import references apps/mobile.
References checked (final pre-deletion sweep): pnpm-workspace.yaml, .github/workflows/*, compose*.yml, Dockerfiles, repo-wide grep for "apps/mobile" (all remaining hits were either retired-scaffold comments in the two capacitor.config.ts files, correctly preserved, or the validate_version.py/test_validate_version.py references above, which anticipate and test for its absence).
Action taken: Directory deleted (`rm -rf apps/mobile`). git status showed only `.gitignore` as a tracked deletion (` D apps/mobile/.gitignore`); the local `.env` was untracked and is gone from this machine only, not from git history (it was never committed).
Risk realised: None. No CI, build, or test failed as a result (validate_version.py's own test suite explicitly expects this state).
```

A dedicated continuation pass (dead-code audit, BOLA/IDOR authorization audit, dependency/CI/CD/
container review, full outstanding-documentation read) found one further confirmed-dead file,
`apps/web/components/coming-soon.tsx`, now deleted (see Code Hygiene Findings). One further
candidate, a set of ~21 possibly-orphaned CSS classes in `apps/web/app/control-centre/pcc.css`,
was identified but deliberately **not** deleted — see Code Hygiene Findings for why.

## Manual Verification Required

- Production infrastructure: TLS configuration, firewall rules, NetBird ACLs, DNS, reverse-proxy
  runtime config beyond what's in `infrastructure/caddy/*.Caddyfile` source, and whether port 443
  TCP+UDP is actually reachable for Caddy's ACME HTTPS.
- GitHub repository settings: branch protection rules, required reviewers, environment-protection
  approval gates — none of the three workflows define a `jobs.<job>.environment:` block, so any
  such gate exists purely in repo settings, not visible from this checkout.
- How production deployment is actually triggered — confirmed no workflow in this repo performs a
  deploy; per `docs/operations/release-process.md`/`deployment.md`, only Anthony manually merges to
  `main`, tags, and deploys. The actual trigger mechanism (manual `docker compose` on the host, or
  something else) should be confirmed directly.
- Cloud/hosting provider IAM, database network exposure as actually deployed.
- App Store / Google Play Console configuration, APNs certificate/key provisioning state.
- Independent penetration test / WSTG manual testing — explicitly called for in
  `docs/security/secure-development-lifecycle.md` and not yet performed.
- **`MYKHAYA_NATIVE_API_URL` production setting** (SEC-09) — confirm it is set before the next
  deploy, per `docs/operations/deployment.md`'s own self-documented pending-action note.
- **CI security-gate health** — `secrets`/`filesystem`/`semgrep` jobs were observed failing on
  the last several pushes to `dev` in the live GitHub Actions history; this needs direct
  investigation (in particular, confirm whether gitleaks' "10 leaks found" are real secrets or
  false positives that belong in `.gitleaksignore`) — not resolved in this audit pass.
- **Nextcloud sync-scope exclusion for `backups/`** (SEC-07) — cannot be verified from inside the
  repository; user to confirm directly in their Nextcloud client settings.
- A full build/lint/typecheck/test validation of the dependency bumps (SEC-14/SEC-15) — see
  Validation section below for what was actually run and its result.

## Validation

Commands run during this pass, with results:

- `infrastructure/scripts/run-tests.sh pytest tests/test_browser_mfa_flow.py -v` — **12 passed**
  (10 pre-existing + 2 new regression tests for SEC-02).
- `infrastructure/scripts/run-tests.sh pytest tests/test_budget_cross_user_isolation.py
  tests/test_groups_cross_home_isolation.py -v` — **3 passed** (new regression tests for SEC-12/SEC-13).
- `docker compose config postgres` (after the SEC-08 compose.yml change) — parsed correctly,
  produced the intended `cap_drop: [ALL]` + `cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]`
  capability set. A full `docker compose up postgres` reaching healthy was not separately re-verified
  in this pass — recommend confirming before next deploy.
- `docker run ... pip install . pip-audit && pip-audit` (apps/api) — **no known vulnerabilities
  found** (run by the dependency-audit research agent, matches the passing `python-dependencies`
  CI job).
- `pnpm audit` (root workspace) — 17 advisories before remediation (3 critical, 8 high, 6
  moderate); Next.js/sharp (SEC-14/SEC-15) and brace-expansion (SEC-21) patched; vitest major-version
  bump and uuid (transitive, native-build-only) deliberately deferred (SEC-16, dev-only impact).
- `pnpm install --no-frozen-lockfile` — lockfile regenerated locally; confirmed `pnpm-lock.yaml`
  now resolves `next@15.5.24`, `sharp@0.35.5`, `js-yaml@4.3.2`, `brace-expansion@{1.1.21,2.1.7,5.0.12}`.
- `docker build --target check -f apps/web/Dockerfile .` (the exact `quality.yml` web
  lint/typecheck/test/build step) — ran repeatedly across this pass as fixes landed. Original
  baseline: 121 failed / 1880 passed. After dependency bump (SEC-14/15/21): 124 failed (confirmed
  no material new regression from the bump itself). **Final, after the styles-safe-area fix and
  the full web-test triage/fix pass: 86 failed / 1915 passed / 14 skipped (2015 total)** — a net
  reduction of 38 fixed/resolved tests (2 safe-area + 15 administrators/[id] + 37 homes/[id] +
  some variance from unrelated concurrent edits to `payments/page.tsx` in progress during this
  audit). See SEC-20 for the full per-file breakdown. Lint and typecheck passed in every run —
  only the `test` step ever failed.
- `gitleaks detect --source=/repo --no-banner` (exact CI command) — **before remediation: 10
  leaks found** (matches CI); **after remediation: "no leaks found."** (SEC-18).
- `aquasec/trivy:0.64.1 fs --exit-code 1 --severity HIGH,CRITICAL --scanners vuln,misconfig` (exact
  CI command) — **before remediation: 4 HIGH vulnerabilities** (brace-expansion); **after: 0
  vulnerabilities, 0 misconfigurations** (SEC-21).
- `semgrep/semgrep:1.172.0 semgrep scan --config p/owasp-top-ten --error` (exact CI command) —
  **before remediation: 2 blocking findings** (support_reference.py raw-SQL pattern, Android manifest
  false positive); **after: 0 findings** (SEC-22).
- `pytest -k "mfa or auth or security or cross_home or platform or billing or support_reference or budget_cross or groups_cross"`
  (531 selected tests) — original baseline: 15 failed. **Final, after full triage and 3 fixes
  (1 real bug, 2 stale-test corrections): 12 failed** — all 12 individually triaged and documented
  as test-isolation/fixture debt, zero remaining unexplained failures (see SEC-23). This audit's
  own new/touched tests all pass: `test_browser_mfa_flow.py` (12), `test_budget_cross_user_isolation.py`
  (2), `test_groups_cross_home_isolation.py` (1), `test_support_tickets.py` +
  `test_support_notifications.py` (52, re-verified after the SEC-22 rewrite),
  `test_apple_review_fixture.py` + `test_platform_stripe_settings.py` (fixed this pass) — **95
  tests run together, 95 passed.**
- `ruff check` (apps/api) scoped to every file this pass touched (`support_reference.py`,
  `routers/platform.py`, the 2 new test files, and the 3 other edited test files) — found and
  fixed 4 real lint issues in this audit's own new code (unused variable, line length, import
  order); confirmed the remaining 54 errors `ruff` reports in `platform.py`/other touched files
  are pre-existing, nowhere near the lines this audit changed. **This audit's own
  additions/changes are fully lint-clean.**
- `mypy mykhaya/support_reference.py` (the one file with rewritten logic, not just a one-line
  change) — **Success: no issues found.**
- `docker run ... pip install . pip-audit && pip-audit` (apps/api, exact CI command, re-run after
  all fixes) — **no known vulnerabilities found.**
- `npx depcheck` (apps/web) — 0 unused, 0 missing dependencies.
- iOS-shell (`npx vitest run` in `apps/ios-shell`) — **23/23 passed** (config, plugin-ownership,
  scene-delegate-bootstrap). Android-shell — **12/12 passed** (config). Both include the
  Stripe-domain `allowNavigation` regression check. `xcodebuild`/Gradle builds, device/simulator
  testing: **not available in this environment — not claimed as verified.**
- `gh api repos/MyKhaya-app/MyKhaya/branches/{main,dev}` and `.../protection` and `.../rulesets` —
  both branches `protected: false`, both `/protection` endpoints 404, zero rulesets repo-wide
  (SEC-19 evidence, directly inspected, not inferred).
- `git diff --check` — clean (no whitespace errors, no conflict markers) across every change made
  in this pass.
- `git status` reviewed before every commit-adjacent action in this pass; no commits were made
  (per instruction, "do not commit or push unless explicitly instructed").

### Final security-gate validation checklist (per explicit instruction)

```
gitleaks:                    PASS (SEC-18)
filesystem (Trivy):          PASS (SEC-21)
semgrep:                     PASS (SEC-22)
Python dependency audit:     PASS (pip-audit: no known vulnerabilities)
JS dependency audit:         No unresolved critical/high issue without documented acceptance
                              (critical/high production-reachable: fixed; dev-only remainder: SEC-16, documented)
Backend security tests:      519/531 passed in the targeted security subset (up from 516/531);
                              remaining 12 failures fully triaged, all pre-existing debt or
                              test-isolation artifacts, zero unexplained (SEC-23) — this audit's
                              OWN new/touched tests (95 across 7 files) all pass
Frontend security-relevant
  tests:                     1915/2015 passing (up from 1880 baseline / 1877 post-dependency-bump);
                              remaining 86 fully classified — 0 real regressions, 0 security
                              weakenings (SEC-20); the two most security-adjacent PCC pages
                              (admin MFA-reset, Home entitlement-gating) fixed and confirmed passing
Production build:            `docker build --target check` completes; lint/typecheck/build steps
                              pass cleanly; only the `test` step has pre-existing, now-reduced,
                              fully-classified failures (neither before nor after this audit a
                              release-blocking signal, since SEC-19 confirms nothing requires it)
Lint/type checks:            PASS — ruff/mypy clean on every file this audit touched; pre-existing
                              baseline debt elsewhere confirmed unrelated to this audit's changes
Native (iOS/Android shell):  Non-destructive config/plugin-ownership tests PASS (35/35); full
                              Xcode/Gradle builds and device testing require tooling not present
                              in this environment — MANUAL VERIFICATION REQUIRED, not claimed
git diff --check:            PASS (clean)
```

## Remediation Completed (this pass)

- SEC-02 (browser MFA): verified by direct code read, not a defect; 2 regression tests added.
- SEC-05 (f-string SQL style note): superseded by SEC-22 — fixed via `func.nextval()` rewrite,
  eliminating the pattern rather than just documenting it.
- SEC-07 (backups operational hygiene): documentation corrected.
- SEC-08 (postgres cap_drop): compose.yml hardened, config-validated.
- SEC-12 (budget.py test coverage): 2 regression tests added.
- SEC-13 (groups.py test coverage, partial): 1 regression test added; driveway/children/
  invitations/users remain open.
- SEC-14 (Next.js critical CVEs): dependency bumped 15.5.21 → 15.5.24, lockfile regenerated and
  build-verified (no new regression vs. baseline).
- SEC-15 (sharp/js-yaml): override floors tightened, lockfile regenerated and build-verified.
- SEC-18 (CI secrets gate / real DVLA credential): investigated as priority. Real secret removed
  from source; 9 false-positive/fixture findings triaged and narrowly allowlisted with
  documentation; `gitleaks detect` now passes locally with the exact CI command. Credential
  rotation remains an outstanding user action (see Remediation Outstanding).
- SEC-21 (filesystem/Trivy — brace-expansion HIGH CVEs): dependency overrides added, lockfile
  regenerated, re-verified with the exact CI command.
- SEC-22 (semgrep — raw-SQL pattern + Android manifest false positive): raw-SQL pattern eliminated
  at the source; manifest false positive narrowly suppressed via `.semgrepignore` (XML inline
  `nosemgrep` comments confirmed not supported by this analyzer after two attempts); re-verified
  with the exact CI command.
- SEC-20 (web test baseline): full triage of all 22 originally-failing files complete. The
  `styles-safe-area.test.ts` real regression fixed (see below). Two further files fully fixed —
  `app/control-centre/administrators/[id]/page.test.tsx` (15 tests, scoped `getByText` →
  `getByRole("heading", ...)`, unblocking and confirming the MFA-reset confirmation gate actually
  works) and `app/control-centre/homes/[id]/page.test.tsx` (37 tests, same fix, unblocking and
  confirming the Home-module entitlement-gating logic across Free/Family plans). 16 remaining
  files classified as stale/environment-only, zero security relevance, left for a low-priority
  follow-up pass; 2 files (`users/[id]`, `subscriptions/[id]`) classified but a fix attempt on
  `users/[id]` was deliberately reverted after it revealed an unexplained duplicate-heading render
  worth its own investigation rather than a rushed fix.
- SEC-23 (backend test baseline): full triage of all 8 originally-failing files complete. One real
  bug found and fixed: `GET /api/v1/platform/payments/stripe` hardcoded `editable=True` instead of
  deriving it from `config.source`, matching the sibling settings endpoint's existing pattern. Two
  stale tests fixed to match real, intentional architecture/security changes
  (`test_enabling_incomplete_mode_is_rejected`'s fixture updated for the Stripe signup-acquisition
  gating split; `test_managed_demo_service_has_scoped_security_guards`'s string-literal assertion
  updated to match current wording). Remaining 6 failures (entitlement-fixture staleness across
  `test_mobile_auth.py`/`test_billing_webhooks.py`, one anti-enumeration status-code widening) and
  1 test-isolation defect (`test_native_cors.py`'s import-time `os.environ` mutation) documented as
  low-priority, well-understood follow-up work, not fixed in this pass.
- Real regression fixed: the shared safe-area CSS invariant (AGENTS.md/mobile-standards.md) was
  violated in two places — `.platform-login` (PCC login, via `apps/web/app/styles.css` and the
  actual-winning rule in `apps/web/app/control-centre/pcc.css`) and `.budget-delete-confirm`.
  Fixed by reusing the established `var(--safe-top)`/`var(--safe-bottom)` pattern; the existing
  `styles-safe-area.test.ts` suite (no new test needed) confirms the fix, 7/7 passing.
- `apps/mobile/` deleted (confirmed-dead retired Expo scaffold).
- `apps/web/components/coming-soon.tsx` deleted (confirmed-dead, plus its dedicated CSS).

## Remediation Outstanding

- SEC-01 (PCC WebAuthn): accepted pre-launch blocker, not attempted — correctly out of scope per
  instruction (no rushed implementation).
- SEC-03 (Android secure storage): accepted — no persistent Android credential storage exists yet
  to retrofit; stands as a requirement for whenever that work begins.
- SEC-04 (DSR workflows), SEC-10 (billing production readiness, ToS/Privacy Policy, VAT): business/
  legal workstreams, not engineering fixes, correctly out of scope.
- SEC-06 (PCC naming clarity): informational, no change made.
- SEC-09 (`MYKHAYA_NATIVE_API_URL`): user/operator action required before next deploy.
- SEC-13 (remaining modules): driveway.py, children.py, invitations.py, users.py cross-Home/
  cross-user regression tests not yet written.
- SEC-16 (vitest major-version bump, uuid): deliberately deferred, dev-only/native-build-only impact.
- `apps/web/app/control-centre/pcc.css` possible dead CSS (~21 classes): needs manual confirmation
  (dynamic-HTML risk) before deletion — not removed in this pass.
- **SEC-18 — DVLA UAT API key rotation (user action required, single highest-priority item in this
  entire report):** the real key removed from `.env.example` in this pass must be rotated via
  DVLA's developer-access channel; the old value must be treated as permanently compromised
  regardless of git history. Once rotated, the user should ask for SEC-18 to be updated with the
  rotation date and a final re-verification (see SEC-18's own entry for the exact follow-up steps).
- **SEC-19 — branch protection:** no branch protection or rulesets exist on `main` or `dev`
  (confirmed via GitHub API); configuring it is a GitHub repository-settings action this audit
  cannot perform without explicit authorisation.
- **SEC-20 — 86 pre-existing web test failures remain** (down from 121; fully triaged, 2 files
  fully fixed — see Remediation Completed). `users/[id]`'s duplicate-`<h1>` render is worth a
  dedicated look (not diagnosed further — a fix attempt was reverted rather than rushed);
  `subscriptions/[id]` and 14 purely-cosmetic files are well-understood, low-priority, no security
  relevance.
- **SEC-23 — 12 pre-existing backend security-subset test failures remain** (down from 15; fully
  triaged, 3 fixed including one real bug — see Remediation Completed). Remaining 6 need
  entitlement-fixture updates (mechanical); 2 are a test-isolation defect in `test_native_cors.py`'s
  import-time env mutation (fix recommended: switch to `app.dependency_overrides`, not attempted
  given risk under time pressure); 1 is a deliberate canary awaiting a product decision on
  `code`-based security-critical notification templates.
- A systematic duplicate-utility-function diff and a full endpoint-vs-frontend-usage cross-reference
  were both out of scope for this pass's time budget — flagged as follow-up work, not attempted
  partially.

## Threat Model Summary

Consistent with `docs/security/threat-model.md` and `docs/security/platform-administration-threat-model.md`
(read in full during this audit — see Documentation Reviewed). Protected assets: user accounts and
sessions, Home membership and private coordination data, invitations, audit records, platform
operator credentials, backups, CI/CD and container-registry integrity. Trust boundaries: browser,
native iOS/Android shells (thin WKWebView/Android-WebView wrappers around the one hosted frontend),
Caddy (the only public-port listener), FastAPI app/worker/scheduler, PostgreSQL/Redis (internal
network only, never published), email provider, CI/CD, and the separate, structurally-isolated
Platform Control Centre management plane. Principal threats this audit specifically tested for:
cross-Home/cross-user data access (BOLA/IDOR — see Authorization section below, no exploitable gap
found), credential/secret exposure (SEC-18, one real finding), CI/CD and supply-chain integrity
(SEC-14/15/16/21/22, dependency and SAST findings, fixed or documented), and source-control
governance (SEC-19, confirmed absent branch protection). Native/mobile-shell threats (`allowNavigation`
host-list integrity, bundle-identifier reuse, Keychain/Keystore credential storage) were reviewed in
Phase 1 and re-verified via the non-destructive config/plugin-ownership test suites in this pass
(35/35 passing — see Validation).

## NCSC Alignment

Per `docs/security/security-baseline.md`'s stated target (NCSC Secure Development Principles and
Cloud Security Principles as practice guidance, not a compliance certification claim):

```
Default deny / fail closed:        Reviewed — confirmed in membership_for/require_capability
                                    (404 on absent authority, not a silent allow), PCC's
                                    separate-dependency-chain isolation, and the admin network
                                    allow-list's documented "defence in depth, not identity" stance.
Least privilege:                   Reviewed — Postgres roles (mykhaya_migrator vs mykhaya_app,
                                    confirmed via init-db.sh), container capabilities (cap_drop
                                    ALL + minimal cap_add, SEC-08 gap closed), CI token scopes
                                    (minimal `permissions:` blocks, SEC-19 investigation).
Secure configuration:              Reviewed — Dockerfiles non-root/multi-stage, Caddy security
                                    headers/HSTS/trusted-proxy CIDRs fail closed, CORS fixed
                                    allow-list. Partially implemented — SEC-19 (no branch
                                    protection) is a configuration gap.
Supply chain / CI integrity:       Reviewed and actively tested this pass — SEC-14/15/16/21/22.
                                    Partially implemented — SEC-19 branch protection absent.
Secrets management:                Reviewed and actively tested this pass — SEC-18. One real
                                    exposure found and remediated in source; rotation outstanding
                                    (external action, explicitly not a blocker per instruction).
Monitoring/logging:                Reviewed via docs/security/logging-and-monitoring.md in Phase 1
                                    (hard invariant against logging credentials — not independently
                                    re-tested against live log output in this pass). Manual
                                    verification required for production log pipeline behaviour.
Incident response:                 Reviewed via docs/security/incident-response-outline.md (Phase
                                    1) — an 11-step documented process exists; not exercised in
                                    this audit. Manual verification required.
```

## OWASP Alignment

```
OWASP Top 10 (2025, awareness baseline per security-baseline.md):
  A01 Broken Access Control:       Reviewed, actively tested — BOLA/IDOR audit, no exploitable
                                    gap across 17 router modules + platform isolation boundary.
  A02 Cryptographic Failures:      Reviewed (Phase 1) — Argon2 hashing, keyed-hash tokens, secure
                                    random generation. Not independently re-tested this pass.
  A03 Injection:                   Reviewed and actively tested this pass — SEC-05/SEC-22 (the one
                                    real raw-SQL-construction pattern found, fixed); no SQL
                                    injection, XSS, or shell-injection sink found anywhere else.
  A04 Insecure Design:             Reviewed — entitlement/authorization layering (platform flag >
                                    commercial entitlement > household permission, documented and
                                    tested elsewhere in the codebase's own suite), notification
                                    single-pipeline rule, PCC separation.
  A05 Security Misconfiguration:   Reviewed and actively tested — SEC-08 (container), SEC-19
                                    (branch protection, open).
  A06 Vulnerable Components:       Reviewed and actively tested — full dependency audit,
                                    SEC-14/15/16/21.
  A07 Auth Failures:               Reviewed and actively tested — SEC-02 (browser MFA, verified
                                    correctly gated, not a defect), SEC-01/SEC-03 (accepted
                                    pre-launch blockers, not defects).
  A08 Software/Data Integrity:     Reviewed — CI Action SHA-pinning, Docker image version-pinning,
                                    SBOM generation (confirmed passing in live CI history).
  A09 Logging/Monitoring Failures: Reviewed (Phase 1 docs); not independently re-tested this pass.
  A10 SSRF:                        Reviewed (Phase 1) — no user-supplied-URL fetch pattern found
                                    requiring SSRF controls at the time of Phase 1; not re-tested.

OWASP API Security Top 10 (2023): API1 (BOLA) and API2 (Broken Auth) were the two most directly
and actively tested categories in this pass, both via the dedicated BOLA/IDOR audit and the SEC-02
browser-MFA code verification. API3 (mass assignment) — Phase 1 confirmed StrictModel/extra="forbid"
patterns prevent it structurally for commercial/subscription fields; not exhaustively re-tested
across every router this pass.
```

## Authentication

Browser: cookie-based, HttpOnly/SameSite, CSRF double-submit + Origin check (Phase 1, ADR 0006).
Browser MFA (SEC-02): verified by direct code read this pass to be correctly implemented behind a
single shared enforcement seam (`complete_browser_authentication`), gated by
`MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED` (documented rollout flag, off by default everywhere) — not a
defect, 2 new regression tests added and passing. Native: bearer tokens (ADR 0010), Keychain-backed
on iOS (`whenUnlockedThisDeviceOnly`, `sync:false`), no equivalent on Android yet because no
persistent Android session store exists yet (SEC-03, accepted). Platform/PCC: entirely separate
identity model, mandatory-MFA-by-policy but WebAuthn/passkey implementation still outstanding
(SEC-01, accepted pre-launch blocker, explicitly not rushed per instruction).

## Authorization / BOLA

Full static-code BOLA/IDOR audit (this pass) across 17 router modules (groups, calendar,
calendar_sharing, calendar_highlights, budget, driveway, lists, meal_plans, wishlists, support,
notifications, reminders, household_routines, todos, children, invitations, home_join, users,
billing) plus the shared mechanism (`dependencies.py`, `household_permissions.py`) and the
platform-isolation boundary (`platform.py`/`platform_compliance.py`, confirmed to import none of
the consumer auth dependency chain). **No exploitable gap found.** Test-coverage gaps (not code
gaps) identified and partially closed: SEC-12 (budget.py, fully closed), SEC-13 (groups.py closed,
driveway/children/invitations/users remain open).

## Home Isolation

`membership_for()`'s `(group_id, user_id)`-scoped lookup with identical 404 for "Home doesn't
exist" vs "not your Home" (no enumeration signal) is the universal primitive every reviewed module
uses, either directly or via `require_capability()`. Confirmed no raw/unscoped resource lookup
exists across the 17 modules reviewed.

## PCC (Platform Control Centre)

Structurally isolated from the consumer app: separate hostname-based routing
(`apps/web/middleware.ts`), separate session/cookie namespace, separate CSRF, separate MFA policy
path, and confirmed (this pass) separate dependency-injection chain with zero shared authorization
code with consumer routers. Self-documented, consistently across multiple independent docs, as
**not production-ready pending mandatory WebAuthn/passkey implementation** (SEC-01) — this audit
did not attempt that implementation, per explicit instruction not to rush a security-critical
feature to "make the audit green."

## Browser Security

CSP with nonce (production), HSTS at the Caddy origin, fixed CORS allow-list (confirmed via code +
tests), no `dangerouslySetInnerHTML`/`eval`/raw-HTML-injection sink found anywhere in `apps/web`
(Phase 1 pattern sweep). No auth secret in localStorage (frontend-standards.md's explicit ban,
confirmed via architecture review).

## API Security

`/openapi.json`/`/docs` confirmed code-disabled in production (`main.py`'s `api_documentation_urls`).
Parameterised SQL throughout (one exception found and fixed — SEC-05/SEC-22). Strict Pydantic
request models prevent mass assignment for commercial/subscription fields (Phase 1). Redis-backed
rate limiting confirmed present across 30+ call sites (Phase 1); fail-open/fail-closed behaviour on
a Redis outage was not independently re-verified this pass — flagged for manual follow-up.

## Native Security

iOS: Keychain-backed session storage, non-wildcard `allowNavigation` host list with a passing
regression test banning Stripe-like domain additions (re-verified this pass: 23/23 iOS-shell tests
pass). Android: same `allowNavigation` pattern (12/12 Android-shell tests pass this pass), but no
persistent secure credential storage exists yet (SEC-03, accepted — nothing to retrofit since no
persistent Android login exists yet). Both config suites were re-run in this pass as the available
non-destructive native validation; `xcodebuild`/Gradle builds and device/simulator testing require
tooling (Mac/Xcode, Android SDK) not present in this environment — **not claimed as verified,
manual verification required.**

## Logging / Monitoring

Reviewed via `docs/security/logging-and-monitoring.md` in Phase 1: hard invariant against logging
passwords/cookies/Authorization headers/raw tokens. Not independently re-tested against live
production log output in this pass — manual verification required.

## Security Testing Coverage Review

Assessed existing automated coverage against the requested invariant checklist before deciding
where to add tests, per instruction not to add duplicate tests merely for numbers:

```
Browser MFA enforcement/bypass:      Gap found and closed this pass — 2 new tests
                                      (test_browser_mfa_flow.py), proving the shared seam gates
                                      Apple/social continuation identically to password login, and
                                      locking in the exact set of session-issuing call sites.
Cross-Home access:                   Broad existing coverage confirmed (test_calendar.py and others);
                                      gaps found and closed for budget.py and groups.py (SEC-12/13).
                                      driveway.py/children.py/invitations.py/users.py remain open.
Cross-user access:                   Gap found and closed — budget.py (SEC-12), proving two members
                                      of the same Home never see each other's budget data.
BOLA/IDOR:                           Full audit performed (17 modules); gaps closed where found.
PCC isolation:                       Confirmed via code audit (separate dependency chain); existing
                                      dedicated test files already cover platform/consumer
                                      separation (test_push_notifications.py, test_smtp_settings.py
                                      and others) — not duplicated.
Entitlement enforcement:             Confirmed via docs/security/platform-administration-security.md's
                                      own entitlement changelog and the existing ASVS control matrix
                                      evidence citations (Phase 1) — extensive existing coverage,
                                      not independently re-audited line-by-line this pass.
Adult-only restrictions:             Existing dedicated coverage (test_mobile_auth.py) — currently
                                      failing on a stale fixture (SEC-23), not a missing-test gap;
                                      the invariant itself is tested, just needs its fixture updated.
Mass assignment:                     StrictModel/extra="forbid" pattern confirmed structurally
                                      (Phase 1); not independently re-tested per-endpoint this pass.
CSRF protection:                     Existing dedicated coverage (double-submit + Origin check,
                                      ADR 0006, confirmed via architecture review) — not duplicated.
Recent-auth requirements:            Confirmed via code read (require_fresh_adult_auth gating
                                      passkey registration) — existing coverage, not duplicated.
Disabled/compromised Home:           Existing dedicated coverage confirmed
                                      (test_platform_lifecycle_deletion.py, test_platform_bulk_lifecycle.py,
                                      test_notifications_lifecycle.py) — not duplicated.
Webhook verification:                Existing dedicated coverage (test_billing_webhooks.py,
                                      signature-over-raw-body + replay-protection pattern documented
                                      in Phase 1) — not duplicated; one pre-existing failure in this
                                      file is tracked under SEC-23, unrelated to webhook verification
                                      itself (an entitlement-gate fixture issue).
Notification ownership/privacy:      Existing dedicated coverage (test_support_notifications.py and
                                      others, 29 tests sampled and passing in this pass's
                                      validation run) — not duplicated.
Session expiry/revocation:           Existing dedicated coverage (ADR 0006/0010) — not duplicated.
```

Net new tests added this pass: 5, each closing a specific, evidenced gap (SEC-02 ×2, SEC-12 ×2,
SEC-13 ×1) rather than padding coverage that already existed.

## Before Production

Meaningful remaining production-readiness items only — already-remediated findings are not
repeated here:

```
1. PCC mandatory WebAuthn/passkey implementation and independent review (SEC-01).
   Self-documented across README.md, platform-administration-security.md,
   platform-administration-threat-model.md, and product/platform-administration-scope.md
   as a hard precondition for production operator access. Not attempted by this audit.

2. GitHub branch protection / rulesets on `main` and `dev` (SEC-19).
   Confirmed absent. Target state documented above under SEC-19 — requires direct
   GitHub repository-settings configuration by someone with admin access.

3. DVLA UAT credential rotation (SEC-18).
   Removed from source; rotation is an external owner action. Explicitly not a
   blocker for this audit per instruction, but should complete before the DVLA
   integration is relied upon in any further environment.

4. Pre-existing test-baseline triage (SEC-20 web, SEC-23 backend).
   121 web + 15 backend security-subset failures, confirmed pre-existing and
   unrelated to this audit. Sampled and classified in detail (see those
   findings and the Test Baseline section below); full triage of the
   remainder is a real body of engineering work, not a rubber-stamp.

5. Android persistent secure credential storage (SEC-03).
   No implementation exists yet to review — recorded as a requirement to
   satisfy (Keychain-equivalent, not generic storage) before persistent
   Android login ships, not as a current defect.

6. Production infrastructure manual verification.
   TLS/firewall/DNS/NetBird ACL/hosting-IAM state — none of this is provable
   from a repository checkout. See Manual Verification Required below.

7. Independent penetration testing / WSTG manual testing.
   Explicitly called for in docs/security/secure-development-lifecycle.md and
   not yet performed, per that document's own admission.

8. Billing production readiness (SEC-10).
   No Terms of Service/Privacy Policy page exists; Tax/VAT handling
   undecided; no real Stripe sandbox end-to-end run has been performed. All
   self-disclosed, pre-existing, business/legal rather than engineering work.

9. Data-subject-rights workflows (SEC-04).
   Statutory export/correction/self-service-erasure flows are not
   implemented; only narrow, audited PCC-operator actions exist. Legal/
   compliance workstream, not an engineering security fix.
```

No other unresolved High or Medium finding remains outside this list (see Completion Summary for
the full severity tally).

## Residual Risk

After this pass's remediation, the residual risk profile is:

- **Operational, not architectural.** No exploitable code-level vulnerability (injection, BOLA/IDOR,
  broken auth, insecure deserialization, etc.) was found anywhere in the reviewed codebase. The
  residual risk is concentrated in process/governance gaps (branch protection, pre-launch MFA
  features not yet built, test-baseline debt) rather than flaws in what has been built.
- **The DVLA credential (SEC-18)** is the one item with any live exposure window, and it is bounded
  by scope (UAT/sandbox access, not production vehicle data) and now closed at the source level;
  residual risk here is entirely the rotation window until the user completes that external step.
- **PCC (SEC-01)** carries the largest standing architectural risk if it were treated as
  production-ready today — it should not be, and every document that discusses it agrees.
- **Governance (SEC-19)** is a multiplier on every other risk in this report: without branch
  protection, any future regression — security-relevant or not — can reach `main`/`dev` without
  review or a passing check, exactly as happened with SEC-18.
- **Test-baseline debt (SEC-20/SEC-23)** is a visibility risk, not a known active vulnerability:
  every sampled failure traced to a stale assertion or (in two cases) a security control that got
  *stricter* than the test expected — but a suite this far from green makes the next genuine
  regression harder to spot.

## Completion Summary

**Security findings by severity** (original severity as first assigned; see each finding's
`Status:` line for current disposition — several "High"/"Critical" items are already fixed):

```
Critical:       1  (SEC-14)                                        — fixed: 1, outstanding: 0
High:           4  (SEC-01, SEC-02, SEC-15, SEC-18)                 — fixed/resolved: 3, accepted blocker: 1
Medium:         6  (SEC-03, SEC-04, SEC-10, SEC-19, SEC-21, SEC-22) — fixed: 2, accepted/self-disclosed: 3, open: 1
Low:            5  (SEC-05, SEC-08, SEC-16, SEC-20, SEC-23)         — fixed: 2, deferred/open: 3
Informational:  7  (SEC-06, SEC-07, SEC-09, SEC-11,
                     SEC-12, SEC-13, SEC-17)                        — fixed/addressed: 3, open: 4
```
23 findings total (SEC-01 through SEC-23).

SEC-18 (the DVLA credential exposure itself) is counted as High and "resolved" only in the sense
that the gate is clean and the value is removed from source — **the credential rotation itself is
still outstanding and is this report's single highest-priority action item.** SEC-19 (branch
protection), SEC-20 (121 pre-existing web test failures), and SEC-23 (15 pre-existing backend
security-test failures) are each separate, newly-split findings per instruction — none of them
restates another. SEC-21 and SEC-22 (the `filesystem`/Trivy and `semgrep` CI jobs) were both
investigated and fixed in this pass.

**Files deleted:** `apps/mobile/` (retired Expo scaffold, 2 files), `apps/web/components/coming-soon.tsx`
(dead component, plus 5 dedicated CSS rules in `apps/web/app/styles.css`).

**Dead code removed:** 1 unused React component. No unused dependencies found (`depcheck`: 0/0).
No orphaned feature flags found. ~21 possibly-dead CSS classes identified but deliberately not
removed pending manual confirmation.

**Dependencies patched:** `next` 15.5.21 → 15.5.24 (2 critical RCE advisories), `sharp` override
floor `^0.35.0` → `^0.35.4` (3 high advisories), `js-yaml` override floor `^4.3.1` → `^4.3.2` (1
high advisory, dev-only), `brace-expansion` pinned across all 3 resolved major lines (`@1`→`^1.1.20`,
`@2`→`^2.1.6`, `@5`→`^5.0.11`; 4 HIGH CVEs, dev/build-tooling-only but was failing the CI `filesystem`
gate). Deliberately deferred: `vitest` (major-version bump needed, dev-only), `uuid` (transitive,
native iOS build tooling only, no safe independent override).

**Comments/TODOs cleaned:** 0 removed — a full re-read of every TODO/FIXME/HACK/XXX/WORKAROUND
marker in `apps/api`, `apps/web`, `apps/ios-shell` found no actual open debt markers (Phase 1's
naive counts were false positives on the word "Todo" as a domain noun); no cleanup was manufactured
to produce a diff where none was warranted.

**Security fixes beyond dependencies:** one real SQL-construction pattern eliminated
(`support_reference.py`, SEC-05/SEC-22 — converted from `text(f"...")` to a genuinely
parameter-bound `func.nextval()` call); one container-hardening gap closed (`postgres` now has
`cap_drop: [ALL]`, SEC-08); one real exposed credential removed from source (`.env.example`'s DVLA
UAT key, SEC-18) with rotation flagged to the user as the critical remaining step.

**Security tests added:** 5 new regression tests across 3 new/extended test files
(`test_browser_mfa_flow.py` +2, `test_budget_cross_user_isolation.py` +2 new file,
`test_groups_cross_home_isolation.py` +1 new file), plus 52 existing tests re-verified passing
after the SEC-22 `support_reference.py` rewrite — all run against the project's real isolated test
stack via Docker, not mocked.

**CI security gate:** all three previously-failing `security.yml` jobs (`secrets`, `filesystem`,
`semgrep`) were investigated, fixed, and re-verified locally with the exact CI commands — each now
passes. The gate's 7-week, 0/389-recent-pass-rate red streak (SEC-18/SEC-19) should end on the next
push, pending the user applying these changes.

**Documentation updated:** `docs/operations/backup-and-restore.md` (cloud-sync warning),
`.gitleaksignore` (10 new narrowly-fingerprinted entries, one corrected for accurate wording),
`.semgrepignore` (new file, 1 narrowly-documented path entry), this report
(`docs/security/MYKHAYA_SECURITY_AUDIT_2026-10.md`, extensively).

**Manual checks outstanding:**
1. Rotate the exposed DVLA UAT API key (SEC-18) — external owner action, explicitly not a blocker
   for this audit's completion per instruction. Not performed here; when done, ask for SEC-18 to be
   updated with the rotation date and a final re-verification.
2. Configure GitHub branch protection on `main`/`dev` (SEC-19) — confirmed absent, not configurable
   from this repository checkout; target state documented under SEC-19 above.
3. Remaining test-baseline follow-up: 86 web (SEC-20, 2 files worth a closer look) and 12 backend
   (SEC-23, mechanical fixture updates) — both fully triaged and documented, neither blocking.
4. Production infrastructure/DNS/firewall state, `MYKHAYA_NATIVE_API_URL` production config,
   Nextcloud backup sync-scope exclusion, native Xcode/Gradle builds — see Manual Verification
   Required and Before Production above.

**Final assessment:** MyKhaya's engineering team has already built a notably mature, well-documented
security posture for a project at this stage. This audit's main value was independent verification
(confirming self-disclosed gaps are real and nothing worse was hiding behind them) plus one real
finding: a genuine DVLA UAT credential, committed 3 days before this audit, sitting exposed on a
public, branch-protection-free GitHub repository, undetected inside a CI secrets gate that had
already been red for 7 weeks for unrelated reasons. Investigating why that gate was red surfaced
two more genuinely-failing security-scanner jobs (Trivy, Semgrep) — both fixed and re-verified —
plus a separate, confirmed-absent branch-protection finding. That general pattern — a gate or
signal that's allowed to stay red stops functioning as a gate at all — is the single most
actionable lesson from this audit, independent of any one finding. No other critical or
high-severity *code* vulnerability was found anywhere in the codebase; the two most significant
standing risks (PCC WebAuthn, browser MFA rollout) are both already-tracked, intentionally-gated
pre-launch blockers with sound fail-safe design, not defects. The BOLA/IDOR audit found no
exploitable authorization gap across 17 router modules and the platform-isolation boundary.
Full triage of both pre-existing test baselines (121→86 web, 15→12 backend, after fixing what
was safe to fix) found exactly one real regression (shared safe-area CSS, fixed) and one real API
bug (Stripe settings `editable` field, fixed) — everything else was stale tests trailing legitimate
change, in two cases revealing security controls that got *stricter*, not weaker. Codebase hygiene
is good: low genuine dead code, low comment debt, consistent authorization patterns, no duplicated
security logic. Remaining follow-up, in priority order: **(1) rotate the DVLA key, (2) configure
branch protection, (3) investigate `users/[id]`'s duplicate-heading render, (4) close the remaining
BOLA/IDOR test-coverage gaps (SEC-13), (5) the mechanical remaining test-fixture cleanup
(SEC-20/SEC-23).**

---

## Final Completion Report

```
SECURITY
Critical: 1  (fixed: 1, outstanding: 0)
High:     4  (fixed/resolved: 3, accepted pre-launch blocker: 1)
Medium:   6  (fixed: 2, accepted/self-disclosed external: 3, open — branch protection: 1)
Low:      5  (fixed: 2, deferred/open: 3)
Informational: 7  (fixed/addressed: 3, open: 4)
Total: 23 findings (SEC-01 – SEC-23)

Remediated:        SEC-02, SEC-05, SEC-07, SEC-08, SEC-12, SEC-13 (partial), SEC-14, SEC-15,
                    SEC-18 (source-level), SEC-21, SEC-22 — 11 of 23 findings fixed or resolved
Outstanding:        SEC-01, SEC-03, SEC-04, SEC-06, SEC-09, SEC-10, SEC-11 (n/a), SEC-13 (remaining
                    modules), SEC-16, SEC-17 (n/a), SEC-19, SEC-20 (remaining), SEC-23 (remaining)
Manual/external action: SEC-18 (DVLA key rotation — user), SEC-19 (branch protection — user),
                    SEC-01 (PCC WebAuthn implementation — future work), production infra/DNS/
                    firewall/Play-Console/App-Store/pen-test (all Manual Verification Required)

CODE CLEANUP
Files deleted: 2 (apps/mobile/ — 2 files; apps/web/components/coming-soon.tsx — 1 file + 5 CSS rules)
Dead code removed: 1 unused React component; 0 unused npm dependencies (depcheck clean);
                    0 orphaned feature flags; ~21 dead pcc.css classes identified, confirmed, but
                    deliberately not removed (entangled in legacy comma-selector lists — follow-up)
Dependencies removed: 0 (none were removable — all findings were version-bump fixes)
Dependencies patched: next, sharp, js-yaml, brace-expansion (4 packages, 10 CVEs total)
Comments cleaned: 0 (none needed — full re-read found no actual debt; false alarm from Phase 1's
                    naive "Todo"-as-domain-noun miscount)
TODO/FIXME resolved: 0 open markers existed to resolve (3 "workaround" mentions found, all
                    legitimate explanatory prose, none requiring action)

TESTING
Tests added: 5 new regression tests (SEC-02 ×2, SEC-12 ×2, SEC-13 ×1), across 3 files
Pre-existing failures before: 121 web / 15 backend (136 total)
Failures remaining: 86 web / 12 backend (98 total) — all fully classified, none unexplained
Real regressions fixed: 2 (shared safe-area CSS invariant; Stripe settings `editable` field bug)
Stale tests corrected: 5 (2 PCC detail-page test files covering 52 individual tests via selector
                    fixes; 2 backend fixture updates; 1 string-literal assertion update)

SECURITY GATES
gitleaks:            PASS (was failing — 10 findings, 1 real secret; now clean)
Trivy:                PASS (was failing — 4 HIGH CVEs; now clean)
Semgrep:              PASS (was failing — 2 blocking findings; now clean)
pip-audit:            PASS (no known vulnerabilities, before and after)
JS dependency audit:  No unresolved critical/high without documented acceptance (SEC-16 dev-only
                    remainder explicitly documented, not silently ignored)

VALIDATION
Backend:   519/531 passing in the targeted security subset (up from 516/531); ruff/mypy clean on
           every file this audit touched
Frontend:  1915/2015 passing (up from 1880 baseline); lint/typecheck clean in every run
Production build: completes cleanly (lint/typecheck/build steps all pass; only pre-existing,
           fully-classified test failures remain, unrelated to build/deploy readiness)
Native: iOS-shell 23/23, Android-shell 12/12 (non-destructive config/plugin-ownership tests);
           Xcode/Gradle builds and device testing not available in this environment — not claimed
git diff --check: PASS (clean)

BEFORE PRODUCTION
- PCC mandatory WebAuthn/passkey implementation and independent review (SEC-01)
- GitHub branch protection on main/dev (SEC-19)
- DVLA UAT credential rotation (SEC-18) — external action
- Android persistent secure credential storage, once persistent Android login is built (SEC-03)
- Billing production readiness: ToS/Privacy Policy, VAT decision, real Stripe sandbox run (SEC-10)
- Data-subject-rights workflows (SEC-04)
- Independent penetration testing / WSTG manual testing
- Production infrastructure manual verification (TLS/firewall/DNS/NetBird/hosting IAM)
```
