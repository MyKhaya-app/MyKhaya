# Apple TestFlight review fixture

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
