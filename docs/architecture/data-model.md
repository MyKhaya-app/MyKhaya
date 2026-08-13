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

A user may belong to multiple Homes. Every Home-owned entity must be queried through an authorised Home context. Managed Child profiles do not receive adult login accounts by default.

## Household relationship and authority

`group_memberships.relationship` describes the person's place in a Home: Home Admin, Partner, Child, Extended Family or Friend. It is deliberately separate from `permission_profile`, capability overrides and explicitly shared resources. Code must authorize against central capabilities, never infer authority directly from a relationship label.

Home Admin is the full household-administration profile. Partner receives ordinary Calendar collaboration without household administration. Extended Family and Friend use explicit sharing. Child authority comes from a managed `child_profiles` record and restrictive permission switches. The final active Home Admin cannot be demoted or removed.

Migration `0006_household_relationships` maps legacy owner/administrator memberships to Home Admin. All other historical roles become `review_required`; personal relationships are not guessed. Existing memberships, invitations, Calendar data and feature overrides are preserved, and the migration has a downgrade path.

Managed Child profiles store an age band rather than a full date of birth and have explicit guardian assignments to active Home Admin or Partner memberships. They have no adult invitation or authentication identity. Permission, age-band, guardian and transition-review changes require confirmation, reason and audit. Anonymisation revokes access and replaces identifying account fields.
