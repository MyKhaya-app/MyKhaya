# Multi-Tenancy

The internal tenant boundary is a `group`; the user experience calls the primary group a Home or Khaya.

Tenant protection uses defence in depth:

1. Current membership checks
2. Central authorisation services
3. Home-scoped repository methods
4. Database constraints
5. PostgreSQL row-level security where clear and maintainable
6. Cross-tenant automated tests

Avoid unsafe methods such as `get_by_id(id)` for tenant-owned entities. Prefer operations equivalent to `get_for_group(group_id, entity_id)` after deriving or verifying authorised context.
