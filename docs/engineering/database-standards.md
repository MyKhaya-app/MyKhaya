# Database Standards

- PostgreSQL is required from the first commit; SQLite is not an application database option.
- Every shared record carries `group_id` or an equivalent explicit Home ownership key.
- Use UUIDv7 where reliable; never expose sequential identifiers.
- Store timestamps in UTC with timezone awareness.
- Enforce foreign keys, unique constraints and explicit delete behaviour.
- Index actual access paths, normally beginning with `group_id` for tenant-owned resources.
- Use Alembic migrations; never modify production schema manually.
- Application runtime credentials must not be database superuser credentials.
- Use connection pooling, statement timeouts and bounded transactions.
- A Docker volume is not a backup. Restore tests are mandatory.
