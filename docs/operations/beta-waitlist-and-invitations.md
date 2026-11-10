# Founding Beta waitlist and invitation email operations

The public Founding Beta waitlist confirmation and the PCC-issued invitation
email both use the Notification Engine and the durable `notification.email`
outbox. Their templates are registered in the PCC notification-template area:

- `founding_beta_waitlist_confirmation`
- `founding_beta_invitation`

Both messages are mandatory email workflows, so recipient preferences cannot
silently suppress them. Delivery is visible in PCC Communications diagnostics
by filtering the notification type. Temporary SMTP failures follow the normal
bounded worker retry policy; an active Beta invitation can also be safely
resent by an Owner or Administrator. Resending refreshes the expiry and queues
the same derived invitation link again, preserving the existing one-time
redemption and avoiding a second reservation.

The API never returns the raw invitation token to PCC. The token is derived
from the invitation identifier and environment secret immediately before the
email is queued; audit records contain only the invitation identifier and
programme metadata. No migration is required for these notification-template
or delivery-path changes.

Local tests prove queueing, rendering, idempotency, token rotation and the
existing expiry/redemption checks. They do not prove live DEV SMTP/provider
delivery. After deployment, verify the DEV email configuration, worker and
SMTP/provider delivery records in PCC Communications before treating the live
flow as confirmed.
