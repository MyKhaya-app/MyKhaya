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

The invitation email uses the shared branded email wrapper's “Accept your
invitation” action button and retains the resolved URL as a plain-text fallback.
The fallback is environment-derived and the displayed expiry is formatted for
recipients rather than exposing an implementation timestamp.

The normal `/register?beta=1&beta_invitation=…` screen remains the only new-account
registration experience. A valid, unexpired invitation bound to the submitted
email may pass the deployment-level general-registration-closed gate. PCC's
registration disablement, closed signup mode, domain policy, email verification,
MFA, legal acceptance, Beta Terms, capacity and one-time redemption remain
enforced. Password, Apple and Google registration all use the same server-side
policy decision.

In the iOS and Android apps, `/register?beta=1` hands the Beta intent and any
invitation to native Apple/Google sign-in. Both native start requests
(`POST /auth/mobile/external/start` and `/auth/mobile/external/browser/start`)
accept `beta` and `beta_invitation_token`; the token is only valid with
`beta`, and Beta is rejected on a link request. The API hashes the token on
arrival and keeps only its SHA-256 with the short-lived sign-in record, so the
raw token is never stored, returned or logged. Whether the sign-in may create
an account uses the same `_beta_signup_allowed` check as web, and
`/auth/mobile/external/recovery/register` re-checks it before creating the
account. Native registration also requires a verified provider email,
matching web Google. A successful Beta registration records the Beta
legal-acceptance context and the same `BetaPendingRegistration` as web, so the
app resumes the Beta continuation after sign-in. The registration request
itself never carries Beta fields.

### Follow-up: Apple "Hide My Email" and email-bound invitations

**Status:** open. Logged 2026-11-12. Behaviour unchanged.

A Beta invitation is bound to the email it was sent to, and every invited
registration checks the provider email against it (web and native, Apple and
Google). If an invited person chooses **Hide My Email** in the Apple sheet,
Apple returns a private-relay address (`…@privaterelay.appleid.com`). That
address never matches the invitation, so the choose step offers only "I
already have an account" with the generic copy:

> New account creation is currently unavailable for this Apple sign-in. You
> can still link Apple to an existing MyKhaya account.

That copy does not tell the person what went wrong or what to do instead.

**Proposed user-facing copy (not implemented).** Show it only when the
sign-in carried a Beta invitation and the provider email is an Apple
private-relay address. Showing it needs a reason from the API (for example
`registration_unavailable_reason: "invitation_email_mismatch"`), so it is a
behaviour change for a later, reviewed task.

> **Your invitation is for a different email**
>
> You chose to hide your email from MyKhaya, so we can't match this Apple
> sign-in to your Founding Beta invitation.
>
> To join, go back and sign in with Apple again, choosing **Share My Email**
> and the address your invitation was sent to. You can also create your
> account with that email address and a password.
>
> [Try Apple again] [Use email instead]

The copy deliberately does not reveal which address the invitation was sent
to. The secondary action returns to `/register?beta=1` with the invitation, so
the email form can be used.

**Options for the behaviour change, for the Owner to decide:**

1. Copy only, as above. Lowest risk; the person must share their real email.
2. Let a signed-in relay account redeem an invitation by proving it can read
   the invited address (an emailed code). This keeps relay addresses for
   everyone else and does not weaken the email binding.
3. Bind invitations to a one-time token alone. This weakens the current
   control and is not recommended.

### Physical-device check (native Beta sign-up)

Automated tests mock the providers, so run this on DEV with a physical iPhone
(Apple uses the SDK flow, Google the system-browser flow) and, when available,
a physical Android phone. Use test provider accounts whose email has no
MyKhaya account, and set DEV to a Beta-only signup mode that requires
invitations.

1. In PCC, issue a Beta invitation to the provider account's email. Open the
   invitation link on the phone so the app shows `/register?beta=1` with the
   invitation.
2. Tap **Continue with Apple**. Complete the Apple sheet. The choose step shows
   the **Founding Beta** badge with "I'm new to MyKhaya" selected.
3. Tick the Terms checkbox and tap **Create account**. Complete MFA if
   prompted. The app opens the Founding Beta welcome (Beta Terms and Home
   enrolment), not `/home` or the paid-plan onboarding.
4. Repeat with **Continue with Google**. The system browser opens and returns
   to the app, with the same result.
5. Negative checks:
   - With an invitation issued to a *different* email, the choose step offers
     only "I already have an account".
   - Without `beta=1` during the Beta-only period, the choose step offers only
     "I already have an account".
6. In PCC, the new users show a pending Beta enrolment. The API logs for these
   requests contain no invitation token.

Local tests prove queueing, rendering, idempotency, token rotation and the
existing expiry/redemption checks. They do not prove live DEV SMTP/provider
delivery. After deployment, verify the DEV email configuration, worker and
SMTP/provider delivery records in PCC Communications before treating the live
flow as confirmed.
