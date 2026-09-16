# Known test debt

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
