# One-off DEV → PROD Home migration

The existing CLI remains the underlying migration engine. PCC adds a protected
operator interface around that same engine. It moves one Home
from a development database into a production database using fresh database
IDs. It never connects the DEV process to the PROD database.

## PCC operator workflow

Home Migration is disabled by default and restricted to platform owners and
administrators. Enabling it, generating an export, and performing a real
production import require recent authentication; all actions are audited.

In DEV, enable **Enable Home Migration** in PCC Settings, open
**Operations → Home Migration**, select a Home, preview the export, then
generate and download the package. In PROD, enable the setting, upload the
package, inspect it, run its checksum-bound dry-run, and type the exact
migration ID to confirm the import. Disable the setting when finished.

DEV and PROD never connect directly: the manually moved, checksum-validated
package is the only transport. PCC exposes no database/API/storage bridge,
remote credentials, or “send to PROD” action. Uploaded packages use the
controlled `MYKHAYA_HOME_MIGRATION_STORAGE_DIR` path and should be removed
under the deployment retention policy after use.

## DEV export

Run locally against the DEV API configuration:

```bash
python -m mykhaya.tools.home_migration export \
  --home-id <HOME_UUID> \
  --output ./migration-packages/home.json
```

The package contains personal data and bounded copies of local avatar, vehicle,
and meal-image bytes. Encrypt it during transfer and delete it after the import.

## PROD validation and import

On the PROD host/container, run the dry-run first:

```bash
python -m mykhaya.tools.home_migration import \
  --input ./migration-packages/home.json \
  --target-environment prod \
  --dry-run \
  --report-dir ./migration-reports
```

Only when the report says `READY_TO_IMPORT`:

```bash
python -m mykhaya.tools.home_migration import \
  --input ./migration-packages/home.json \
  --target-environment prod \
  --confirm \
  --report-dir ./migration-reports
```

The import is transactional and records the package migration ID in
`home_migration_ledger`; reusing a completed package is refused. New accounts
receive no DEV credential. They have a randomly generated unusable password
hash, receive the normal PROD email-verification message when verification is
required, and then establish their own password through the normal password
reset flow. Existing users matched by normalized email are not overwritten.

The utility copies Home content, memberships, safe profiles, calendars,
household activity, meals, lists, wishlists, budgets, vehicles, child records,
notification preferences, Home feature/settings state, and internal
complimentary entitlement state. It excludes credentials, sessions, tokens,
MFA/passkeys, push/delivery/operational records, audit/PCC/platform records,
Beta operational records, retention state, Stripe IDs/events, and all secrets.
The Home holiday subscription is excluded because its catalogue source is a
platform-owned environment record and cannot be safely remapped by Home ID.

Stripe is never contacted and no charge is created. Source Stripe references
are removed from the package and target subscription state contains no external
provider identifiers. Unsupported or missing asset files make the operation
fail safely; they are never silently dropped. Supplying `--report-dir` writes
both `migration-report-<id>.json` and `migration-report-<id>.txt`.

After validating the Home and account activation requirements, securely delete
the package and any generated report copies from both environments.
