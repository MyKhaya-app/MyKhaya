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

## Commercial entitlements — household Plan & Billing (Phase 4)

Full architecture in `docs/architecture/commercial-entitlements.md`'s "Phase 4" section.

### `billing_manage` requirement

Unchanged from Phase 3: only `Capability.billing_manage` (home_admin only) can start Checkout or open the Customer Portal. Phase 4 adds no new mutating endpoint, so no new permission surface exists — the polished page calls exactly the same two Phase 3 write endpoints. A member without `billing_manage` sees the same read-only `BillingStatusResponse` as anyone else in the Home (see "household-safe billing response" below); the frontend hides the action buttons for them, but this is presentation only — the backend `require_capability` check is what actually stops the request, so a non-manager calling the endpoints directly still gets 403, not a silently-hidden-but-reachable action.

### No browser-based entitlement activation

Reaffirmed from Phase 3: the success redirect from Stripe Checkout carries no authority. The Phase 4 page's delayed one-shot re-fetch after returning from Checkout is a UX affordance only — it calls the same authenticated `GET /groups/{id}/billing` any other page load would, which itself only ever reflects whatever `apply_stripe_subscription_state` has already committed from a verified webhook. There is no code path, in Phase 4 or earlier, where a query string or client-side timer writes to `HomeSubscription`.

### Household-safe billing response

`BillingStatusResponse` is deliberately narrow. Confirmed excluded, by construction (the response model has no such field, not by a filtering step that could regress): `complimentary_note`, `HomeSubscriptionEvent` history, `StripeWebhookEvent`/webhook event IDs, raw Stripe Customer/Subscription objects, `MYKHAYA_STRIPE_SECRET_KEY`/`MYKHAYA_STRIPE_WEBHOOK_SECRET`, and `external_customer_id`/`external_subscription_id` themselves (the household page has no use for the raw Stripe identifiers — only the derived `price`/`billing_interval`/dates it actually renders). Covered by `test_billing_status_response_never_exposes_internal_or_secret_fields`. `GET /billing/plans` and `GET /billing/pricing` return only plan-comparison/pricing data — no Home-specific or provider-secret information at all, so they're safe to leave public/unauthenticated, matching Phase 3's existing pricing endpoint.

### No payment credential storage

Unchanged: no card number, CVV, or bank credential is collected or stored by MyKhaya at any point in the Phase 4 UI — Checkout and the Customer Portal are the only surfaces that ever see payment details, and both are Stripe-hosted, opened via a plain redirect (never an iframe).

### No arbitrary provider/plan mutation

Phase 4 adds zero new write endpoints. The household Plan & Billing page can only ever trigger the same two actions Phase 3 already gated: start Checkout (`interval` only) and open the Portal. There remains no `PATCH /groups/{id}/billing` or equivalent — commercial state still only ever changes via a verified Stripe webhook or the Platform Control Centre's Complimentary/reconciliation actions.

### IDOR

`GET /groups/{id}/billing` resolves the caller's membership via `membership_for(group_id, auth, db)` (the same dependency every other Home-scoped household endpoint uses) and 404s for a Home the caller doesn't belong to — a user cannot view, let alone manage, another Home's billing state. Covered by `test_user_cannot_view_another_homes_billing_state`.

## Commercial entitlements — public pricing and signup/onboarding (Phase 5)

Full architecture in `docs/architecture/commercial-entitlements.md`'s "Phase 5" section. Phase 5 adds no new endpoint, no new capability, and no new write path — it is a new pre-login UI in front of already-public read endpoints and the existing registration/Home-creation/Checkout endpoints, used in their existing order.

### Public plan intent is untrusted

The plan/interval a visitor picks on the homepage travels only as a `?plan=&interval=` query string into `/register` and, from there, an opportunistic `localStorage` hint (`apps/web/components/onboarding-intent.ts`) read back by the onboarding plan step. Both the query-string parser and the stored-value reader constrain every value to a closed enum (`free`/`family`, `month`/`year`) and silently fall back to the safe default (`free`/`month`) for anything else — an out-of-enum, malformed, or tampered value is never surfaced as an error, it's just treated as no selection. Neither value is ever sent to `POST /auth/register` or `POST /groups` — see "No plan activation via query/frontend" below — so even a maximally adversarial value here has no path to commercial effect; the worst case is the wrong card being preselected on a screen the visitor is about to look at anyway.

### No plan activation via query or frontend state

`RegisterRequest` and `GroupCreate` (the schemas behind `POST /auth/register` and `POST /groups`) are both `StrictModel` (`extra="forbid"`) and accept no plan/provider/status field at all — a request body containing `{"plan": "family", "provider": "stripe", "status": "active"}` alongside valid registration/Home-creation fields is rejected with `422` before any handler logic runs, not silently ignored. `POST /groups` also takes no query parameters it reads; a `?plan=family&interval=year` suffix on the request URL is inert. Every new Home is created through the same `ensure_home_subscription` call Phase 1 established, which takes no plan argument — it always writes `plan=free, provider=free, status=active`. Covered by `test_register_rejects_commercial_fields`, `test_group_creation_rejects_commercial_fields`, and `test_new_home_is_always_free_regardless_of_query_string` (all in `test_signup_commercial_intent.py`).

### No arbitrary Price/amount submission at signup

The onboarding plan step's Family action calls the exact same `POST /groups/{id}/billing/checkout-session` Phase 3 built, sending only `{interval}` — the same client-supplied-amount/Price-ID rejection Phase 3's `test_client_cannot_supply_a_price_id_or_amount` already covers applies unchanged, since no new Checkout code path is introduced.

### Checkout redirect still carries no authority

Unchanged from Phase 3/4: Stripe's success/cancel redirect always points at `/settings/billing` (not back into onboarding), and that page's existing "confirm, then re-fetch once" behaviour is what decides what to show — a query string is never treated as proof of payment anywhere in this codebase, at signup or afterwards.

### Invite-path protection

An invited member reaches `/auth/register` with `invitation_token` set but never `POST /groups` — they join the inviter's *existing* Home via the already-authenticated `POST /invitations/accept`, which only ever creates/reactivates a `Membership` on the invitation's stored `group_id` and never touches that Home's `HomeSubscription`. `apps/web/app/register/page.tsx` additionally ignores `?plan=`/`?interval=` outright whenever an `invitation` token is present, so an invite link cannot be crafted to imply a purchase. Covered by `test_invited_member_joins_existing_home_without_a_new_home_or_plan_choice`, which asserts the joined Home's stored plan/provider/status are byte-identical before and after.

### Public endpoint exposure

`GET /billing/pricing` and `GET /billing/plans` are unchanged from Phase 3/4 — both remain public, rate-limited (`billing-pricing`/`billing-plans`, 60/60s), read-only, and expose no Stripe Price ID, Customer/subscription data, or provider secret; see the Phase 4 section above ("Household-safe billing response") for the exhaustive exclusion list, which Phase 5 introduces no exception to. The homepage and onboarding plan step call these two endpoints and nothing else unauthenticated.

## Commercial entitlements — feature entitlement enforcement and safe downgrades (Phase 6)

Full architecture in `docs/architecture/commercial-entitlements.md`'s "Phase 6" section.

### Server-side enforcement is authoritative

Every calendar-creation/-mutation endpoint enforces its limit/restriction in `mykhaya/routers/calendar.py` itself, not only in frontend conditionals. `apps/web/app/calendar/calendars/page.tsx`'s "Add a calendar" form hiding behind an upgrade CTA is UX only — a direct `POST /homes/{id}/calendars` call from a Free Home at its limit is rejected with `403` regardless of what the frontend would have shown, and a direct `POST /homes/{id}/events` targeting a read-only-due-to-plan `calendar_id` is rejected the same way. Covered by every test in `apps/api/tests/test_calendar_entitlements.py`, which exercises the HTTP layer directly rather than any frontend state.

### Direct API protection cannot be bypassed by permission or plan alone

Three properties are independently tested, matching the three-layer authorization order: (1) a disabled Calendar feature flag blocks access even on a Family-entitled Home (`test_disabled_calendar_feature_blocks_access_even_on_family`) — commercial entitlement never overrides a platform-level module disablement; (2) a Family entitlement never grants permission to a member who lacks it (`test_family_entitlement_does_not_grant_permission_to_an_unauthorised_member`) — entitlement is additive to availability, never to authorization; (3) full permission (Home Admin) never bypasses a commercial limit (`test_free_home_admin_still_cannot_exceed_the_limit`).

### Race-condition protection

`create_calendar` acquires a per-Home `pg_advisory_xact_lock` before counting existing calendars and enforcing the limit, inside the same transaction as the insert — the identical pattern `routers.billing.checkout_session` already used for concurrent-Checkout protection. `test_concurrent_calendar_creation_cannot_exceed_the_limit` proves this with genuine concurrent HTTP requests against the real test database, not a sequential assertion: five concurrent creation attempts with exactly one slot remaining produce exactly one success and four `403`s.

### Provider-neutral logic and errors

`mykhaya/routers/calendar.py` never branches on `subscription.provider` or `subscription.status` — every check goes through `mykhaya.entitlements.get_limit`/`require_within_limit`/`classify_ordered_resources`, which resolve *effective* plan only. This is directly tested by the commercial-state matrix in `test_calendar_entitlements.py`: Complimentary active, Stripe active, Stripe `past_due`, and Stripe `cancel_at_period_end` all behave identically (as Family), while Complimentary expired and Stripe `cancelled` both behave identically (as Free) — proving Calendar code has no provider-specific paths to audit. The structured `commercial_restriction_error` responses (`plan_feature_unavailable`, `plan_limit_reached`, `resource_restricted_by_plan`) carry only an entitlement key and a numeric limit as metadata — never a Stripe status, a Complimentary reason/note, or an internal subscription/customer/price ID. `test_free_home_second_calendar_is_blocked_with_a_structured_error` asserts neither "stripe" nor "complimentary" appears anywhere in the error body.

### No Stripe call during ordinary feature authorization

Every entitlement check in the calendar-enforcement path (`get_limit`, `require_within_limit`, `classify_ordered_resources`, `calendar_usage`) reads only `HomeSubscription`, MyKhaya's own local row — none of them call `mykhaya.billing` or the Stripe SDK. This preserves the provider-abstraction rule from Phase 1/3: Stripe is only ever consulted for the narrow set of things only Stripe can answer (creating a Checkout/Portal session, resolving a live price, processing a webhook), never for "can this Home do X right now."

### No downgrade deletes data

`DELETE .../calendars/{id}` is the **only** code path in Phase 6 that removes a `HomeCalendar` row (and, via the existing `ondelete=CASCADE`, its events) — and it requires an authenticated, capability-checked, explicitly confirmed (`confirmed: true`) request from a member of that Home. No subscription-state transition (Stripe ending, Complimentary expiring or being revoked, any future path) ever calls it or any other delete. `test_downgrade_preserves_all_calendars_and_restricts_the_excess_ones`, `test_stripe_ended_becomes_free_with_data_preserved`, and `test_complimentary_expired_behaves_as_free_with_data_preserved` each assert the Home's calendar rows are byte-identical (by id) before and after the plan transition.

### No persisted commercial-lock state to drift

`commercial_access` is computed on every read from current entitlement + current calendar ordering — there is no `is_paid_locked`-style column anywhere in the schema for Calendar. This removes an entire class of bug (a stale lock flag surviving a plan change) by construction rather than by careful invalidation logic.

## Commercial entitlements — production billing readiness (Phase 7)

Full architecture in `docs/architecture/commercial-entitlements.md`'s "Phase 7" section.

### Billing launch control is deployment configuration, not a web toggle

`MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED` is an environment variable, restart-required, defaulting `false` everywhere including production — the same trust boundary as the Stripe secrets themselves, deliberately not a Platform Control Centre switch. This means the single most consequential commercial action available to this system (allowing real customers to be charged) requires infrastructure-level deployment access, not a web session — immune to CSRF, session hijack, or an accidental click inside the admin UI. `Settings.validate_stripe_configuration` refuses to start with acquisition enabled but Stripe not fully configured, so the flag can never be "on" in a half-configured state.

### Checkout enforces the gate server-side; nothing trusts frontend hiding

`routers.billing.checkout_session` checks `StripeConfig.acquisition_enabled` itself, after the capability check and before any Stripe call — a direct `POST /groups/{id}/billing/checkout-session` with acquisition disabled is refused with `503` regardless of what the frontend would have shown. `test_checkout_is_refused_while_acquisition_is_disabled` asserts this at the HTTP layer, not by inspecting frontend state.

### Webhook processing is never coupled to the acquisition gate

`POST /billing/stripe/webhook` has no acquisition check at all — verified directly (`test_webhook_processing_unaffected_by_acquisition_disabled`) by disabling acquisition, sending a real `customer.subscription.updated` event for an existing Stripe-backed Home, and confirming it still processes and mutates state. This is a deliberate, tested guarantee: disabling new acquisition must never risk existing subscribers' state going stale.

### Reconciliation authority

`mykhaya.billing.state.apply_stripe_subscription_state` validates a Stripe Subscription object's own `metadata.mykhaya_group_id` against the `group_id` it's being applied to, raising `SubscriptionOwnershipMismatchError` (→ `409`, logged, transaction rolled back) on a mismatch — defence-in-depth against ever attaching one Home's Stripe object to another Home's `HomeSubscription` row, whether from a future code path, a data-integrity bug, or an operator pasting the wrong reference. `test_apply_stripe_state_rejects_a_subscription_whose_metadata_points_elsewhere` / `test_apply_stripe_state_allows_matching_metadata` cover both outcomes directly against the shared function both the webhook handler and manual reconciliation call.

### Provider-ID integrity

`HomeSubscription.external_customer_id`/`external_subscription_id` remain DB-level `UNIQUE` (Phase 3) — a Stripe Customer or Subscription can never resolve to two Homes at the database layer, not merely by application-level convention. `test_a_stripe_customer_id_cannot_resolve_to_two_homes` / `test_a_stripe_subscription_id_cannot_resolve_to_two_homes` assert the constraint fires.

### Checkout/Portal IDOR

Both `checkout_session` and `portal_session` resolve the caller's membership via `membership_for`/`require_capability` exactly like every other Home-scoped endpoint — a non-member gets `404`, matching the app-wide "don't confirm or deny a Home's existence to someone who doesn't belong to it" convention. `test_cannot_start_checkout_for_a_home_you_do_not_belong_to` / `test_cannot_open_portal_for_a_home_you_do_not_belong_to` prove this specifically for the billing endpoints.

### Webhook trust and replay (reaffirmed, not weakened)

Unchanged from Phase 3: `stripe.Webhook.construct_event` verifies the `Stripe-Signature` header against the raw request body using the SDK's default timestamp-tolerance behaviour — never loosened for development convenience, and no code path exists to bypass it. `StripeWebhookEvent.stripe_event_id`'s `UNIQUE` constraint remains the actual dedup mechanism for a successful/ignored event. Phase 7 adds `stripe_webhook_failures` alongside this, not instead of it — a failure is observable but, critically, still never dedupes (see "Webhook observability" in the architecture doc) so Stripe's genuine retry of a previously-failed event is neither silently dropped nor treated as an attacker-replayable bypass: reprocessing only ever happens through `apply_stripe_subscription_state`'s own out-of-order-event guards, never by trusting a bare event ID as proof of anything.

### No card data, no unnecessary payload retention

Unchanged: no card number, CVV, or bank credential ever reaches MyKhaya. `stripe_webhook_events`/`stripe_webhook_failures` both store only enough to dedupe/troubleshoot (event ID, type, timestamps, outcome, a short sanitised error string) — never the raw webhook payload.

### Billing support diagnostics without database access

`SubscriptionDetailResponse.recent_webhook_events` (per-Home, last 10) and `GET /platform/subscriptions/webhook-health` (deployment-wide, last 20 events/failures) exist specifically so a support operator can answer "did Stripe's webhook actually arrive for this Home" without `psql` access — both are `SUPPORT`-role-gated like the rest of the subscriptions area, and neither exposes a raw Stripe payload, a secret, or anything beyond `event_type`/`outcome`/timestamps.

### Security review (this phase)

A targeted review attempted the following against the full public pricing → signup → Checkout → webhook → entitlement → Calendar → Portal → cancellation chain; all held:

- Injecting `plan`/`provider`/`status` via registration or Home-creation payloads — rejected (`StrictModel`, Phase 5).
- Injecting an arbitrary Stripe Price ID or amount into Checkout — rejected (`CheckoutSessionRequest` only ever accepts `interval`, Phase 3).
- Starting Checkout or opening the Portal for a Home the caller doesn't belong to — `404` (this phase, see above).
- Replaying a captured webhook payload without a valid signature — `400`, rejected before any DB work (Phase 3, reaffirmed).
- Replaying a validly-signed, already-processed webhook event — idempotent no-op (Phase 3, reaffirmed).
- Reusing a Stripe Customer/Subscription ID across two Homes — rejected at the database layer (this phase).
- Attaching a Stripe Subscription object to the wrong Home via a metadata mismatch — rejected (this phase, `SubscriptionOwnershipMismatchError`).
- Bypassing the Free calendar limit via concurrent requests — prevented by the per-Home advisory lock (Phase 6, reaffirmed).
- Regaining Family after a genuine Stripe cancellation by relying on stale browser/redirect state — impossible; the browser return is never authoritative, only the webhook-driven `HomeSubscription` row is (Phase 3/4, reaffirmed).

No new bypass was found. No existing protection was weakened to make this review pass.
