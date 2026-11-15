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

## Package upload limit

PCC Home Migration JSON uploads are limited to 50 MiB, including multipart
overhead. This limit is scoped to `POST /api/v1/platform/home-migration/upload`;
the normal 1 MiB API request limit remains unchanged. The API rejects a larger
upload with a 413 response before JSON parsing and reports the supported limit
to the operator. Package validation, checksum verification, source-environment
checks, and migration-ID checks still run for every accepted upload.

Asset bytes included in the package are base64-encoded inside the JSON, so they
increase the transfer size beyond their binary size. The package format is
unchanged; keep unusually large Homes within the documented limit or remove
unneeded local assets before export.

## Container storage

The API runs read-only except for dedicated application-data mounts. Home
Migration packages use `/data/home-migrations`, backed by a persistent named
volume mounted only at that path. The DEV Compose overlay names it
`mykhaya_dev_home_migration_data`; the PROD overlay names it
`mykhaya_prod_home_migration_data`. The volumes are persistent across API
recreation but are never shared between environments and are not served by
the web or Caddy containers. The API image creates the mount point for the
non-root `mykhaya` user; do not replace this with a world-writable directory.

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
complimentary entitlement state and remaps Home holiday subscriptions by the
target platform catalogue's country/region key. It excludes credentials, sessions, tokens,
MFA/passkeys, push/delivery/operational records, audit/PCC/platform records,
Beta operational records, retention state, Stripe IDs/events, and all secrets.

Stripe is never contacted and no charge is created. Source Stripe references
are removed from the package and target subscription state contains no external
provider identifiers. Unsupported or missing asset files make the operation
fail safely; they are never silently dropped. Supplying `--report-dir` writes
both `migration-report-<id>.json` and `migration-report-<id>.txt`.

The package format is version 2. It contains an explicit coverage manifest,
record counts, asset sizes and SHA-256 checksums, source-to-PROD environment
mappings, and the package integrity hash. The PCC stores a separate canonical
checksum; PROD recomputes it immediately before import and refuses any package
that changed after dry-run.

Each Home is migrated independently. For a two-Home cutover, create exactly two
separate packages and complete the full workflow for each package. Never combine
the Homes into one package or reuse a package across Homes. The ledger rejects a
repeated migration ID or source Home ID.

The dry-run returns `READY_TO_IMPORT` only when identity checks, schema coverage,
catalogue mappings and package validation are clear. Any unresolved issue returns
`NOT_SAFE_TO_IMPORT`. A completed import performs reconciliation before the ledger
row is written and reports `VERIFIED` only when record counts, relationships and
asset checksums match.

## Controlled cutover runbook

1. Obtain Owner approval naming exactly two DEV Home IDs. Record both IDs and the
   two independent migration IDs in the change record.
2. Verify the PROD backup and restoration procedure using the normal backup and
   restore runbook. Do not experiment against live PROD.
3. Confirm DEV and PROD are at the same application/Alembic schema revision.
4. Enable Home Migration only in the environment currently being operated.
5. For each selected Home independently, review the export preview and account
   readiness report. Stop on any ambiguous identity, provider-only account,
   verification blocker or shared-membership conflict.
6. Suspend writes to the selected DEV Home through the approved operational
   procedure. Do not change authentication or invent a temporary login control.
7. Export the final package and retain its manifest and checksum in the change
   record. Compare the source Home counts with the manifest.
8. Encrypt the package during manual transfer and upload it to the isolated PROD
   migration storage path. Never use a DEV-to-PROD database/API bridge.
9. Run the PROD dry-run and confirm `READY_TO_IMPORT` for that exact checksum.
10. A second authorised operator reviews the identity, data, file, environment and
    exclusion sections. Type the exact migration ID to confirm.
11. Import the Home. The database transaction and tracked asset cleanup handle
    failures; no source Home is deleted.
12. Confirm the report is `IMPORTED` with reconciliation `VERIFIED`. If it is
    `VERIFICATION_FAILED`, treat the Home as not cut over and stop further work.
13. Perform functional checks using the existing PROD login and Forgotten Password
    process. Existing PROD users must retain their existing authentication and
    memberships.
14. Repeat steps 5–13 for the second package, independently.
15. Disable Home Migration in both environments, record the final reports, and
    securely remove temporary package/report copies according to retention policy.

## Recovery

An import failure rolls back the database transaction and attempts to delete every
asset written during that transaction. If asset cleanup fails, the operation is
not complete: preserve the reported storage keys for an authorised operator to
remove after inspection. Do not run an unrestricted delete or automatic rollback
against PROD.

If the database commits but a later operator check fails, do not delete the Home
or its users automatically. Preserve the ledger, reports and exact impact details;
stop the cutover, restore from the verified PROD backup only through the approved
recovery process, and obtain explicit Owner approval for any destructive action.

The original DEV Home remains intact until the Owner approves final retention or
deletion separately.
