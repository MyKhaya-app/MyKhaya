# Backup and Restore

`make backup` creates a restrictive-permission compressed custom-format PostgreSQL dump under `backups/` and verifies the gzip stream. Copy backups off-host, encrypt them, apply a retention policy, and monitor both creation and transfer. Redis is coordination state and is not the authoritative backup.

Restore testing is mandatory:

1. Start an isolated stack with new volumes and no public ingress.
2. Run `make restore FILE=/absolute/path/to/backup.sql.gz`.
3. Run migrations, start the application, verify readiness, record counts for users/Homes/memberships/audit/outbox, and complete a login plus cross-Home denial check.
4. Record the backup identifier, restore duration, tester and result. Destroy the isolated restored data securely after the test.

A Docker volume, filesystem snapshot without database consistency, or an untested dump is not a backup claim.

## Encrypted platform secrets (SMTP, push, Stripe)

Platform-Admin-managed secrets (SMTP password, push VAPID private key, Stripe Test/Live
secret keys and webhook signing secrets) are stored encrypted in the database via
`mykhaya.secrets_crypto`, using a key derived from `MYKHAYA_SECRET_KEY` — never stored
in the database itself. A database backup/restore therefore only recovers usable
secrets if the restoring environment has the **same** `MYKHAYA_SECRET_KEY` as the
environment the backup was taken from; restoring into an environment with a different
`MYKHAYA_SECRET_KEY` (e.g. a fresh disaster-recovery deployment that generated its own)
restores the ciphertext but leaves it undecryptable (`SecretDecryptionError`), the same
way it would after a deliberate key rotation. The affected settings pages fail closed
(`configured=False`) rather than crash in this case, and the credential must simply be
re-entered — treat `MYKHAYA_SECRET_KEY` as part of what a disaster-recovery runbook
needs to restore alongside the database, not something backups regenerate on their own.
