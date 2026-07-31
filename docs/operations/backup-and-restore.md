# Backup and Restore

`make backup` creates a restrictive-permission compressed custom-format PostgreSQL dump under `backups/` and verifies the gzip stream. Copy backups off-host, encrypt them, apply a retention policy, and monitor both creation and transfer. Redis is coordination state and is not the authoritative backup.

Restore testing is mandatory:

1. Start an isolated stack with new volumes and no public ingress.
2. Run `make restore FILE=/absolute/path/to/backup.sql.gz`.
3. Run migrations, start the application, verify readiness, record counts for users/Homes/memberships/audit/outbox, and complete a login plus cross-Home denial check.
4. Record the backup identifier, restore duration, tester and result. Destroy the isolated restored data securely after the test.

A Docker volume, filesystem snapshot without database consistency, or an untested dump is not a backup claim.
