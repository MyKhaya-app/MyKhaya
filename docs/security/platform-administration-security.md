# Platform Administration Security

Implemented controls include a separate hostname and API namespace, host-only session cookie, Strict SameSite, CSRF, idle/absolute expiry, revocation, deny-by-default network policy, trusted-proxy validation, platform-only roles, bounded queries, strict schemas, recent authentication for sensitive actions, reasons/confirmation, metadata minimisation, secret-shaped audit redaction and a dedicated append-only API trail.

The application exposes no audit update/delete endpoint. Database roles and external log shipping should additionally prevent application operators from altering retained audit data.

Never store passwords, cookies, session/reset/verification tokens, SMTP credentials, API keys or full secrets in events, notes or settings. Mail credentials remain environment-managed and are never returned.

Production blockers: external audit retention/alerting and independent security testing.

## Emergency MFA recovery (break-glass)

`python -m mykhaya.platform_admin_mfa_recovery --email <email>` — for a Platform Administrator who has lost every second factor (passkey, authenticator app, recovery codes) and has no other administrator able to reset them from the Control Centre. Restricted to whoever already has shell/container access to the MyKhaya server; it is a console-only command with no web endpoint or API route, and must never be exposed as one.

Behaviour: prints the target's email, display name, role and active status, then requires the operator to type the administrator's email back exactly before proceeding (no single-key confirmation for a Platform Control Centre account). It then, in one transaction: disables and removes any TOTP secret, deletes every registered WebAuthn credential, deletes every recovery code, and revokes every currently-active session for that administrator — and writes a `SecurityEvent` (`administrator_mfa_reset_via_break_glass_cli`, severity `high`) recording that it ran. It never logs a secret, session token, or credential material; it never signs the administrator in; it never changes their role or the global `MYKHAYA_ADMIN_MFA_REQUIRED` policy. The administrator re-enrols MFA (`mfa_setup_required`) the next time they sign in with their password, if the policy still requires it — which it does unless explicitly changed separately.

Operational implications: this is a genuinely destructive action against the highest-privilege identity in MyKhaya — every session for that administrator ends immediately, including any that were legitimately in use. Only run it when you have independently confirmed, outside of MyKhaya, that the request is genuine (e.g. a known colleague, not just an email in a ticket). Treat the `SecurityEvent` it writes as something to review, not just log.

## Commercial entitlements (Phase 1)

See `docs/architecture/commercial-entitlements.md` for the full model. Security-relevant points:

A household user can never modify their own Home's plan, provider, or status. `GroupUpdate`/`GroupCreate` (`mykhaya.schemas`) are `StrictModel`s (`extra="forbid"`) with no commercial fields, so any attempt to smuggle `plan`/`provider`/`status` through `PATCH /groups/{id}` is rejected as a 422 mass-assignment error before it reaches application logic — no explicit denylist was needed.

`provider=complimentary` can only ever be set by `PUT /platform/homes/{id}/subscription/complimentary`, gated by `require_roles(*OPERATORS)` (owner/administrator only — support and readonly cannot grant or revoke) and `require_recent_auth`, the same pattern used for every other sensitive Control Centre write. Both the grant and revoke endpoints resolve the target Home strictly by the path's `group_id` and 404 on an unknown one — there is no secondary identifier an attacker could substitute to affect a different Home (no IDOR surface beyond the standard "guess a UUID" case, which the existing rate limiting and audit trail cover the same as every other platform endpoint).

Every grant/revoke is written to both `AdministrativeAuditEvent` (via `platform_audit`, action `home.complimentary_granted`/`home.complimentary_revoked`, reason required) and `HomeSubscriptionEvent` (structured before/after plan, provider, status, actor, reason) — two independent, queryable records of who changed what and why.

`complimentary_note` is deliberately excluded from `HomeSubscriptionResponse` fields returned to anything other than the Platform Control Centre — no household-facing endpoint reads `HomeSubscription` at all in Phase 1, so this is enforced by there simply being no such code path yet, not by field-level filtering that could regress. When a household-facing endpoint is added in a later phase, it must not expose `complimentary_note`.

No payment credentials, card numbers, or Stripe secrets are stored anywhere in Phase 1 — `HomeSubscription`'s Stripe-shaped fields (`external_customer_id`, `external_subscription_id`) are opaque identifier strings for Phase 3 to populate later; nothing in this phase writes to them.

## Commercial entitlements — Platform Control Centre subscription management (Phase 2)

Phase 2 (`docs/architecture/commercial-entitlements.md`'s "Phase 2" section) adds `GET /platform/subscriptions/summary`, `GET /platform/subscriptions`, and `GET /platform/subscriptions/{group_id}` — all read-only, all gated by `require_roles(*SUPPORT)` (support/administrator/owner; readonly is excluded from every platform route by definition of the `SUPPORT` tuple). It reuses Phase 1's `PUT`/`DELETE /platform/homes/{id}/subscription/complimentary` for the two write actions (grant, revoke) rather than adding a new mutation endpoint — see "No generic manual subscription editor" below.

**No arbitrary provider/plan/status mutation.** Phase 2 deliberately does not add an endpoint that lets an operator set `plan`/`provider`/`status`/external IDs directly. The only ways any Home's commercial state changes are: Home creation (defaults to Free), the existing grant-complimentary endpoint (always sets `plan=family, provider=complimentary, status=active`), and the existing revoke-complimentary endpoint (always resets to `plan=free, provider=free, status=active`). A future Stripe integration drives state through Stripe webhook-verified events, not a form field an operator can free-type into.

**Recent-auth boundary.** The three new read endpoints require only `require_roles(*SUPPORT)`, matching every other read-only Control Centre listing/detail view (e.g. the existing `homes`/`home_detail`) — `require_recent_auth` is reserved for the two mutating actions (grant/revoke), unchanged from Phase 1, since re-authentication exists to gate state changes, not reads.

**Internal-note privacy.** `complimentary_note` is returned by the two new detail-shaped endpoints (`home_detail`'s `subscription` block and the new `subscription_detail`) exactly as it always was — restricted to Platform Control Centre roles, never by any household-facing route. Phase 2 adds a covering test (`test_internal_note_reaches_platform_admin_but_not_household_endpoints`) that asserts a granted note is both retrievable via the Platform API and absent from the plain household `GET /groups/{id}` response text.

**IDOR / identifier validation.** The list endpoint takes no client-supplied identifier beyond the authenticated operator's own session; the detail endpoint validates `group_id` as a UUID path parameter and 404s on an unknown Home, identical to the Phase 1 pattern. No endpoint accepts a Home identifier from a request body that could be substituted for the path value.

**Scalability, not just correctness.** The summary/list endpoints use single aggregate/joined SQL queries (see the architecture doc's "SQL/Python resolution mirror" section) rather than fetching every Home into the application or issuing one query per row — chosen specifically because MyKhaya is expected to hold significantly more Homes than the existing generic `/homes` browsing endpoint was designed around.

**Audit behaviour is unchanged.** Because grant/revoke still go through Phase 1's existing endpoints, `platform_audit`'s `home.complimentary_granted`/`home.complimentary_revoked` events and the `HomeSubscriptionEvent` history are written exactly as documented in Phase 1 — Phase 2's UI does not, and structurally cannot, bypass them, since there is no alternative write path.

**Confirmed: no household-level route can mutate commercial state.** `GroupUpdate`/`GroupCreate` remain `StrictModel`s with no commercial fields (Phase 1); Phase 2 added zero household-facing endpoints or fields.

## Commercial entitlements — Stripe billing (Phase 3)

Full architecture in `docs/architecture/commercial-entitlements.md`'s "Phase 3" section. Security-specific points:

### Webhooks

`POST /billing/stripe/webhook` trusts exactly one thing: Stripe's cryptographic signature (`stripe.Webhook.construct_event`, computed over the **raw** request body — the route reads `await request.body()` directly rather than a parsed model, since re-serialising a parsed body would not reproduce Stripe's exact bytes and would break verification). An invalid or missing signature is rejected (400) before any database work. There is no IP allowlist as a trust mechanism — Stripe's published IP ranges change, and signature verification is the correct control regardless of source IP. No ordinary authenticated API path can substitute for it: `HomeSubscription.provider = stripe` is only ever set by `apply_stripe_subscription_state`, called exclusively from the webhook handler and the admin-only reconciliation endpoint, both of which resolve state from Stripe's own object, never from client-supplied fields.

Duplicate/replayed events are harmless: `StripeWebhookEvent.stripe_event_id` is unique, checked (with a lock-protected re-check) before any mutation, and a duplicate short-circuits to the previously-recorded outcome without re-processing. A processing failure does not commit a dedup row, so Stripe's retry is never silently swallowed.

### Checkout

`billing_manage` (new `Capability`, `mykhaya/household_permissions.py`) gates both Checkout Session and Customer Portal Session creation — granted only to `home_admin`, not `standard_partner` or any other profile, so an ordinary Home member cannot start Checkout or reach the Portal for a Home merely by being a member. `CheckoutSessionRequest` is a `StrictModel` accepting only `interval: "month" | "year"` — a client cannot supply a Price ID, amount, currency, Stripe Customer, or subscription identifier; all of those are resolved server-side from `Settings`/the Home's existing `HomeSubscription` row. Success/cancel URLs are built from `Settings.public_web_url`, never from a request header. Duplicate-subscription protection (a `_LIVE_STRIPE_STATUSES` check before any Stripe call, backed by a per-Home Postgres advisory lock around the whole operation) prevents a double-click, multiple tabs, or a retried request from creating two active subscriptions for the same Home; a Stripe idempotency key on the Checkout Session creation call is defense-in-depth beneath that.

### Portal

Portal sessions are created only for the Home's own already-stored `external_customer_id` — there is no code path that accepts a Stripe Customer ID from the client, so a Portal session can never be opened against another Home's Stripe Customer (no IDOR surface). `billing_manage` gates this the same as Checkout. The return URL is `Settings.public_web_url`-derived, never client-supplied.

### Data

`MYKHAYA_STRIPE_SECRET_KEY`/`MYKHAYA_STRIPE_WEBHOOK_SECRET` are `SecretStr`, environment-only (no DB storage — see the architecture doc's "Stripe provider boundary" for why this differs from SMTP/push), and never returned by any API response. No card number, CVV, or bank credential is ever stored by MyKhaya — Stripe Checkout and the Customer Portal handle all payment-method collection and display directly; MyKhaya only stores Stripe's own opaque identifiers (`external_customer_id`, `external_subscription_id`, `external_price_id`). `StripeWebhookEvent` stores no payload data, only IDs/timestamps/outcome. `call_stripe`'s error classification (`client.py`) ensures a raw Stripe exception — which can include request/response detail not meant for an API consumer — never reaches a response body; sanitised context goes to the structured server log only.

### Commercial state

Success redirects cannot grant access: `checkout.session.completed` only records IDs, never calls `apply_stripe_subscription_state`. The frontend cannot grant Family under any circumstance — `/settings/billing`'s only state-changing actions are starting Checkout and opening the Portal, both of which redirect to Stripe; there is no client-side write to `HomeSubscription`. Ordinary Home APIs (`PATCH /groups/{id}` etc.) still cannot change provider/status — unchanged from Phase 1/2. `apply_stripe_subscription_state` fails safe on any unrecognised Stripe status (no mutation) exactly as the Phase 1 entitlement resolver fails safe on any unrecognised stored value.

### Paid ↔ Complimentary conflict

`grant_complimentary` now 409s if the Home's `provider == stripe` and `status != cancelled` — an operator cannot accidentally leave a Home simultaneously billed by Stripe and marked Complimentary. See "Complimentary ↔ Stripe transitions" in the architecture doc.
