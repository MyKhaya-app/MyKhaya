# Data Retention

This is the initial policy baseline and requires owner/legal review before production.

| Record | Initial principle |
|---|---|
| Active users/Homes | For the service relationship |
| Suspended users/Homes | Review at least annually; suspension is not indefinite archival authority |
| Closed/deleted accounts | Minimise immediately; anonymise/delete after the reviewed grace period |
| Invitations/action tokens | Expiry plus short abuse-investigation window; remove token material promptly |
| User sessions | Expiry/revocation plus short security window |
| Authentication/security events | 12 months unless an incident/legal need requires a documented hold |
| Administrative audit | 7 years, subject to necessity and legal review |
| Email delivery events | 90 days, excluding message content |
| Background jobs | 90 days; failures up to 12 months where needed for investigation |
| Administrative notes | Review annually and remove when no longer necessary |
| Incidents/maintenance | 3 years for operational learning |
| Backups | Rolling encrypted schedule, target 35 days; documented expiry and restore testing |

Retention automation, legal holds and verified deletion from backups are not yet implemented. Hard deletion from the Control Centre is intentionally unavailable.
