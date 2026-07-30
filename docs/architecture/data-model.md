# Initial Data Model

## Identity

- users
- auth_identities
- sessions

## Home tenancy

- groups
- group_memberships
- group_invitations

## Security and operations

- audit_events
- outbox_events
- worker_job_records where required

A user may belong to multiple Homes. Every Home-owned entity must be queried through an authorised Home context. Child profiles are a future domain concept and do not require login accounts by default.
