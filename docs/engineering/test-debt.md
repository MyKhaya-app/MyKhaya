# Known test debt

## API tests that cannot be rerun against the same database

Several API tests use fixed identifiers, so they pass on a fresh test stack
(how `infrastructure/scripts/run-tests.sh` and CI always run) but fail if rerun
against the same database and Redis. Reproduced 2026-11-08 on the release
candidate:

- `test_mobile_auth.py`: the passkey tests register the fixed credential id
  `AQI` ("That passkey is already registered"). Affected:
  `test_family_passkey_registers_logs_in_revokes_individually_and_keeps_password_fallback`,
  `test_registration_records_the_browser_reported_authenticator_attachment`,
  `test_registration_leaves_attachment_null_when_the_browser_does_not_report_it`
  and `test_passkey_login_honours_required_browser_mfa_policy`.
- `test_native_external_auth.py::test_native_link_is_explicit_and_single_use`:
  the fixed provider subject `native-link-subject`.

Fix by generating these identifiers per test, following the
[deterministic tests](testing-standards.md#deterministic-tests) rule already
applied to `test_concurrent_native_claims_leave_one_provider_owner`.

## PCC metadata fixtures

The API test `test_apple_review_fixture.py::test_managed_demo_service_has_scoped_security_guards`
fails at the Phase 3.6 baseline SHA `002ac3ddae369b3b04413e446cd26e9fbc8ae7b9` and
on the analytics worktree. It expects the string `Refusing to adopt an existing
customer account`, which is absent from the existing managed-demo service.

Representative PCC web tests for `control-centre/users/[id]` and
`control-centre/homes/[id]` likewise reproduce at baseline and current branch
with `TypeError: Cannot read properties of undefined (reading 'configured')`.

These are pre-existing fixture/test-contract failures, not analytics regressions.
They do not block the analytics Phase 4 work, but should be remediated before
claiming the full repository suite is green.
