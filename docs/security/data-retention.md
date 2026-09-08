# Data Retention

This is the initial policy baseline and requires owner/legal review before production.

| Record | Initial principle |
|---|---|
| Active users/Homes | For the service relationship |
| Suspended (Disabled) users/Homes | Review at least annually; suspension is not indefinite archival authority |
| Archived users/Homes | Normal operational retirement mechanism (Control Centre "Archive"). Reversible via Restore. Review at least annually. |
| Closed/deleted accounts | Minimise via Control Centre User anonymisation after the reviewed grace period (see below); full account/data deletion remains a designed requirement, not an implemented capability |
| Invitations/action tokens | Expiry plus short abuse-investigation window; remove token material promptly |
| User sessions | Expiry/revocation plus short security window |
| Authentication/security events | 12 months unless an incident/legal need requires a documented hold |
| Administrative audit | 7 years, subject to necessity and legal review |
| Email delivery events | 90 days, excluding message content |
| Background jobs | 90 days; failures up to 12 months where needed for investigation |
| Administrative notes | Review annually and remove when no longer necessary |
| Incidents/maintenance | 3 years for operational learning |
| Backups | Rolling encrypted schedule, target 35 days; documented expiry and restore testing |

Retention automation, legal holds and verified deletion from backups are not yet implemented.

## Control Centre lifecycle and minimisation actions

Archive remains the normal operational retention mechanism for both Users and Homes: it retires a record from active use while keeping it fully intact and reversible via Restore.

Two narrowly-scoped, PCC-operator-only actions go further than Archive and are **not** reversible:

- **User anonymisation** (`POST /platform/users/{id}/anonymise`). Available only for an already-Archived user. Overwrites the account's direct identifying fields (display name, email, avatar, birth date) with a non-identifying tombstone and permanently revokes every authentication credential and device registration (passkeys, sessions, trusted devices, push subscriptions, action tokens). The `User` row and its `id` are retained, as is historical household content the user created (events, routines, reminders, lists, and similar), so that other members' records and structural attribution stay intact — that content continues to reference the same (now anonymised) user id and is presented in the UI as belonging to "Deleted user". Membership in any Home is ended (soft-removed) as part of anonymisation; historical membership rows are retained. Blocked if the user is the sole Home Admin of a Home with other active members, or is the billing owner of a non-free subscription — either must be resolved first. This is minimisation of personal data in place, not deletion of the account or its historical records, and it cannot be undone.
- **Permanent Home deletion** (`POST /platform/homes/{id}/permanent-delete`). Available only for an already-Archived Home that is genuinely empty: no active or historical membership beyond the unavoidable creator record left by Home creation, no calendar events, routines, reminders, meals, lists, wishlists, calendar shares, invitations or join requests, no non-system calendar labels, no current or historical non-free billing, and no link to a managed demo Home. Any Home with real household history is left to Archive; this action exists only for accidental or disposable test Homes and hard-deletes the Home row (cascading only the automatic scaffolding a Home creation itself produces). The administrative audit record of the deletion (Home id, name, reason) is retained independently of the deleted row.

Both actions require PCC administrative authorisation, recent re-authentication, a documented reason, and an explicit typed confirmation, and both write a permanent `AdministrativeAuditEvent`. Neither action is available in bulk. General User hard-deletion and hard-deletion of a populated Home remain intentionally unavailable from the Control Centre.
