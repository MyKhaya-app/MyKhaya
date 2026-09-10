# Managed Demo & Test Homes

Managed Demo/Test Homes are explicit PCC-managed non-customer environments for
Apple review, demos, QA/UAT and training. PCC operators find them at
`Operations → Demo & Test Homes`. Mutations use the existing PCC operator boundary
(`PlatformRole.owner`/`administrator`), MFA-complete sessions, recent-auth checks,
CSRF protection and platform audit logging; the project has no separate granular
PCC permission registry, so introducing `demo_test_homes.manage` would otherwise
create a parallel authorization model.

The `managed_demo_homes` record is authoritative for fixture ownership and the
stable `fixture_key`; Home names and emails are display data only. Apple Review is
registered as `apple-review` and uses the existing complimentary Family
subscription path with reason `Apple TestFlight review fixture`. It creates no
Stripe subscription. The managed record and subscription are scoped to the same
Home and are removed together by the managed delete path.

Supported types are `apple_review`, `demo`, `qa_test`, and `free_demo`. Apple
Review currently uses the existing canonical sample content. The PCC create
endpoint provisions a verified normal Home Admin account and Home;
template-specific content should be seeded by the corresponding managed
template before external review.

`apple_review`, `demo` and `qa_test` all resolve to a complimentary Family
subscription. `free_demo` ("Free Plan Demo") is the one exception: it resolves
to the real Free plan through the normal subscription/entitlement path (see
`ManagedDemoService.create`), a single-person Home with exactly one Personal
Calendar and exactly two Lists (the Free plan's `lists.max_lists` limit) — a
fixture for validating the actual Free product experience, not a Family demo
with Free-looking data. `ManagedDemoHomeResponse.access` reflects whichever
plan a given fixture actually resolved to ("family" or "free"), not a
hardcoded value.

Expiry is processed by the existing scheduler: it marks the managed record
`expired`, disables only its owner account, and retains Home data and audit history.
It is idempotent. Refreshes must not reactivate an expired/disabled account unless
an operator explicitly enables it.

The fixture is opt-in and is never created during application startup or a migration.
Run it against the intended review environment from the API container:

```text
MYKHAYA_APPLE_REVIEW_PASSWORD='use-a-secret-manager-value' \
  python -m mykhaya.apple_review_fixture create
```

The same command is safe to repeat and refreshes the fixture's relative dates and
sample records. `refresh` is an explicit alias. The account is
`apple-review@mykhaya.app`; the password is only the value supplied through
`MYKHAYA_APPLE_REVIEW_PASSWORD` and is not documented or logged by the command.

To remove it, run:

```text
python -m mykhaya.apple_review_fixture remove
```

Removal is guarded by the stable fixture Home marker and the owner email. It does
not remove a Home with an unrelated marker/name, and it removes fixture users only
when they have no remaining memberships. The review account is a normal Home Admin
(`Role.owner`/`PermissionProfile.home_admin`), not a platform administrator.
Email verification is explicitly satisfied on this fixture user; global email
verification settings are unchanged. No password, token, or bypass is included in
this document. Enter the email and the operator-managed password in App Store
Connect's review information.
