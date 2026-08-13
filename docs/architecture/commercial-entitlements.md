# Commercial Entitlements

Phase 1 of MyKhaya's commercial architecture: plans, Home-level subscriptions and an entitlement-resolution service. Phase 2 ("Platform Control Centre subscription management") builds the read-only-plus-complimentary-only operational UI on top of it. Phase 3 ("Stripe billing", below) adds Stripe as the first real paid billing provider — test/sandbox mode only; see docs/operations/dev-deployment.md#stripe-sandbox. Nothing here builds a public pricing page, a signup payment step, or the polished household Plan & Billing experience — those remain later phases.

## Layering

MyKhaya has three genuinely separate systems that must never be conflated:

1. **Platform Feature Flag** (`mykhaya.features`) — is a module released at all, globally or for this Home.
2. **Commercial Entitlement** (`mykhaya.entitlements`, this document) — does this Home's plan include this capability.
3. **Home/User Permission** (`mykhaya.household_permissions`) — can this particular person, within a Home that already has the feature and the entitlement, actually use it.

A feature only reaches an end user when all three say yes. Routers must check the ones relevant to them explicitly — the entitlement service never consults feature flags or permissions, and vice versa.

## Ownership: the Home, never the user

A subscription belongs to a Home (`Group`), not to an individual user. `HomeSubscription.group_id` is unique — one row per Home. `billing_owner_user_id` records who is nominally responsible for billing (for Phase 3's use, e.g. showing "you manage this Home's plan" in a UI), but it confers no special resolution behaviour in Phase 1: entitlements are resolved from the Home's subscription state alone, never from which user is asking.

## Resolution path

```
Home -> HomeSubscription -> effective_plan() -> PlanDefinition -> entitlements / limits
```

`mykhaya.entitlements.effective_plan()` is the single authoritative function that turns a Home's raw subscription row into a `SubscriptionPlan`. Everything else (`has_entitlement`, `require_entitlement`, `get_limit`, `require_within_limit`) is built on top of it. No other code path may re-derive a plan from raw subscription fields.

**Fails safe throughout:**

- A Home with no `HomeSubscription` row → Free.
- An unrecognised `plan` value → Free.
- A `status` that isn't currently honoured (`cancelled`, or anything not in the honoured set) → Free.
- Complimentary access whose `complimentary_expires_at` has passed → Free.
- An unrecognised entitlement key → not entitled (`False`).
- An unrecognised limit key → `0`, never unlimited.

Family is never the default in any failure path. A bug, a missing row, a bad migration, or a lapsed complimentary grant all degrade to Free, which is always fully functional — never to a broken or blocked state.

`past_due` is deliberately still honoured (the plan stays active). MyKhaya has no payment retry/dunning logic yet — that belongs to Phase 3 — so treating a single missed payment as an instant downgrade would be needlessly harsh before that machinery exists.

## Provider abstraction

`SubscriptionProvider` is `free`, `complimentary`, `stripe`, or the reserved-but-unimplemented `apple`/`google`. `mykhaya.entitlements` never mentions Stripe, Apple, or Google by name in its logic — it asks "what's this Home's plan/entitlement", never "does this Home have a `stripe_subscription_id`". The Stripe-specific fields on `HomeSubscription` (`external_customer_id`, `external_subscription_id`, `current_period_start/end`) exist as storage for Phase 3 but are read by nothing in Phase 1.

## Complimentary access

Complimentary Family access is a first-class MyKhaya concept — `plan=family, provider=complimentary` — not a disguised, zero-cost Stripe subscription. It exists for beta testers, friends and family, and goodwill grants.

- Only a Platform Control Centre operator (`owner`/`administrator` role) can grant or revoke it, via `PUT`/`DELETE /platform/homes/{id}/subscription/complimentary`. No household-facing pathway can ever set `provider=complimentary`.
- `complimentary_reason` is a short, auditable reason. `complimentary_note` is an internal-only field, never returned to or visible from any household-facing endpoint.
- `complimentary_granted_by`/`complimentary_granted_at` record who granted it and when, for accountability.
- `complimentary_expires_at` is optional. When null, access never expires. When set, expiry is evaluated dynamically by `effective_plan()` on every read — there is no scheduled job that "expires" a grant, and none is needed, because resolution always re-checks the timestamp against the current time.

## Structured commercial history

`HomeSubscriptionEvent` records every commercial state transition (`created`, `complimentary_granted`, `downgraded`, and future Stripe transitions) with structured `from_*`/`to_*` plan/provider/status columns plus an optional actor and reason — not free text. This sits alongside, not instead of, the existing audit trails:

- `mykhaya.audit` (`AuditEvent`) still covers ordinary household-scoped activity.
- `mykhaya.platform_audit` (`AdministrativeAuditEvent`) still covers Platform Control Centre actions generally, including `home.complimentary_granted`/`home.complimentary_revoked`.
- `HomeSubscriptionEvent` is the commercial-specific ledger a future billing UI or support tooling can query without parsing audit-event JSON blobs.

## Safe downgrade principle

A commercial downgrade — expiry, cancellation, or an operator revoking complimentary access — **never deletes Home data**. `revoke_complimentary` resets `plan`/`provider`/`status` to Free/free/active and clears the complimentary-specific fields; it does not touch the Home, its members, its calendar, or anything else the Home has created. Free is fully functional by design (one Home, one calendar, useful indefinitely), so a downgrade is a capability change, never a data-loss event.

## Plan definitions

`mykhaya.entitlements.PLAN_DEFINITIONS` is the one place plan capability is defined:

- **Free** (`£0`): `calendar.max_calendars = 1`; `lists`/`chores`/`notes`/`wishlists` entitlements are `False` (those modules don't exist as real features yet — declared as data only, ready for whenever they ship).
- **Family** (`£3.99/mo` or `£39/yr`, or complimentary): `calendar.max_calendars = None` (unlimited); the four booleans above are `True`.

Adding a new entitlement is "add a key to `PLAN_DEFINITIONS`" — never `if home.plan == "family"` scattered through routers. See [Calendar as proof of architecture](#calendar-as-proof-of-architecture) for why nothing calls `require_within_limit` against a real endpoint yet.

## Calendar as proof of architecture

The brief for this phase asked for Calendar to be the first real proof that the entitlement model fits MyKhaya's existing domain model, without inventing a redundant one and without building enforcement against nothing.

Investigation confirmed `HomeCalendar` already has a `(group_id, is_primary)` unique constraint — the schema already structurally supports "at most one calendar per Home" — but **no endpoint exists that can create a second calendar** for a Home. `calendar.max_calendars` is therefore defined as plan data (`1` for Free, unlimited for Family) so the concept is ready, but `require_within_limit` has no live caller in Phase 1. Its docstring documents the concurrency precaution (an advisory lock or `SELECT ... FOR UPDATE` around the count-then-insert, matching `routers.platform`'s `pg_advisory_xact_lock` pattern for the last-Owner check) that whichever future endpoint creates a second calendar must apply — a plain count check without that lock could race two concurrent "create calendar" requests past the limit.

## Migration and grandfathering

Migration `0020_commercial_entitlements` backfills every pre-existing `Group` to `plan=free, provider=free, status=active`. No grandfathering to Family was implemented, and none was needed: no live endpoint in Phase 1 calls `require_entitlement`/`get_limit`/`require_within_limit` against real user-facing functionality (the modules Free restricts don't exist yet; there's no second-calendar endpoint to restrict). Backfilling every Home to Free therefore changes nothing about what any existing Home can actually do today.

## New Home defaults

`routers.groups.create_group` calls `ensure_home_subscription` immediately after creating the Home, its calendar, and its first membership, before the transaction commits — every new Home has an explicit `HomeSubscription` row (Free/free/active) from creation, and requires no payment information.

## Explicitly out of scope for Phase 1

No Stripe SDK, Checkout, webhooks, or customer portal. No payment forms. No pricing pages. No payment step in signup. No Apple/Google in-app billing. No Plan & Billing UI for households. No subscription-management UI in the Platform Control Centre beyond the grant/revoke complimentary endpoints and the read-only subscription block on the existing Home detail page — those exist so Phase 2's UI has something to call, not as the UI itself.

## Phase 2: Platform Control Centre subscription management

Phase 2 adds the operational UI a Platform Administrator needs to actually run Free/Complimentary Homes day to day — still no Stripe, no payment collection, no household-facing billing UI. It is entirely a read layer over Phase 1's data plus two write actions (grant/revoke complimentary) that already existed.

### Stored vs. effective commercial state

The central idea Phase 2 makes visible: a Home's **stored** `HomeSubscription` row (`plan`, `provider`, `status`, and the complimentary fields) is not always what actually applies — `mykhaya.entitlements.resolve_effective_plan`/`resolve_effective_state` (Phase 1) already compute the **effective** plan, honouring expiry and status. Phase 2's UI shows both side by side wherever they might diverge, and a short reason (e.g. "Complimentary access expired") whenever they do — sourced from `resolve_effective_state`'s `reason` field, never recomputed in the frontend. `HomeSubscriptionResponse` gained two additive fields for this: `effective_status_reason` and `complimentary_granted_by_display_name`.

### Read endpoints (`mykhaya.routers.platform`, all under `require_roles(*SUPPORT)`)

- `GET /platform/subscriptions/summary` — aggregate counts (total Homes, effective Free, effective Family, complimentary provider count, expired-complimentary count, past-due count, cancelled count) computed as a **single SQL query** using `COUNT(...) FILTER (WHERE ...)` over one `Group ⟕ HomeSubscription` outer join — not N queries, not a full-table fetch into Python. No revenue/MRR/ARR figure exists here or anywhere else in Phase 2; there is no payment provider yet to source one from.
- `GET /platform/subscriptions` — searchable (`q` against Home name), filterable (`effective` plan, stored `provider`, stored `status`, `expired_complimentary`), paginated Home listing with commercial state and member count, built from one query with two subqueries/joins (member-count aggregation, `HomeSubscription` outer join) rather than a detail request per row.
- `GET /platform/subscriptions/{group_id}` — full commercial detail: Home info, up to 10 Home Admins, the stored+effective subscription block, the resolved `EntitlementsResponse` (booleans + limits for the Home's effective plan), and up to the most recent 100 `HomeSubscriptionEvent` rows with the acting administrator's name resolved.

### The SQL/Python resolution mirror, and why it can't drift silently

Filtering and aggregate-counting by *effective* plan at the database level would otherwise mean either (a) fetching every Home into Python to call `resolve_effective_plan` — which doesn't scale — or (b) writing separate SQL logic that could quietly diverge from the authoritative Python rule as either one changes. `mykhaya.entitlements.effective_plan_sql_filter`/`complimentary_expired_sql_filter` are a deliberate, narrow SQL mirror of `resolve_effective_plan`'s Free/Family split, used **only** for filtering/counting in these two endpoints — never for authorization, which always goes through `resolve_effective_plan`/`effective_plan` on the actual row. `test_effective_plan_sql_filter_matches_python_resolution` (`apps/api/tests/test_entitlements.py`) asserts the two agree across every plan/provider/status/expiry combination that matters, so a future change to one without the other fails CI rather than silently drifting.

### Entitlement viewer

The `entitlements` block in the subscription detail response is `mykhaya.entitlements.PLAN_DEFINITIONS[effective_plan]`, serialised as-is (`EntitlementsResponse`) — the frontend (`apps/web/app/control-centre/subscriptions/[id]/page.tsx`) only maps machine keys (`lists.enabled`, `calendar.max_calendars`, …) to human labels for display; it never re-derives which plan grants which capability. This is Platform Control Centre only — no household-facing endpoint returns a Home's full entitlement map.

### Complimentary grant/revoke UI

The UI calls Phase 1's existing `PUT`/`DELETE /platform/homes/{id}/subscription/complimentary` endpoints unchanged — Phase 2 adds no new write endpoint for commercial state, deliberately. The grant form collects a reason (a small preset list plus free text, not a backend enum — see `mykhaya.platform_schemas.GrantComplimentaryRequest`, which already only required a length-bounded string), an optional internal note, and an expiry (Never, or a specific date/time), then requires the existing `SensitiveActionRequest` reason/confirmation before submitting. "Extend expiry" / "make permanent" / "re-grant" are all the same call to the grant endpoint with a new expiry value — Phase 1's grant endpoint already fully overwrites the complimentary fields, so no separate "update" endpoint was needed. Revoke shows the same safe-downgrade consequence text described above before confirming, and never offers a generic field-by-field editor for `plan`/`provider`/`status`/external IDs (see "No generic manual subscription editor" — deliberately not built, so every commercial state change stays a specific, audited, named action).

### Deferred to Phase 3 (Stripe) or later

Everything under "Explicitly out of scope for Phase 1" above remains out of scope in Phase 2 too. Additionally deferred: a household-facing Plan & Billing page, promotional/coupon codes, a general subscription-management UI beyond complimentary access, and any enforcement of `calendar.max_calendars` against a real create-a-second-calendar endpoint (still doesn't exist).

## Phase 3: Stripe billing

Stripe becomes MyKhaya's first real paid billing provider, sitting entirely behind the `mykhaya.billing` package. It is a provider, not the entitlement engine — nothing outside `mykhaya.billing` asks Stripe anything; every module that cares whether a Home has a feature still calls `has_entitlement`/`require_entitlement`, exactly as before. Stripe's only job is to keep `HomeSubscription.provider/status/current_period_*/external_*` accurate; `mykhaya.entitlements` resolves what that means, unchanged.

### Stripe provider boundary

`mykhaya/billing/` is a self-contained package:

- `config.py` — `resolve_stripe_config(settings) -> StripeConfig` (`source: "environment" | "unconfigured"`, `configured: bool`). **Deliberately environment-only**, unlike SMTP/push, which also support a Platform-Admin-managed DB override — a payment provider's credentials are rotated through infrastructure, not typed into an admin text field, and Stripe secrets never touch the database. `Settings.validate_stripe_configuration` (in `mykhaya/config.py`) refuses to start with a half-configured `MYKHAYA_STRIPE_BILLING_CONFIGURED=true`, and rejects a live key outside production or a test key inside it.
- `client.py` — `call_stripe(func)` runs the (synchronous) Stripe SDK off the event loop via `asyncio.to_thread` (the same pattern `mykhaya.worker` already uses for blocking SMTP/push calls), and classifies `stripe.error.*` into `StripeUnavailableError` (transient — connection, rate limit, misconfigured key) vs `StripeRequestError` (permanent for this request — invalid parameters, declined card).
- `pricing.py` — dynamic Family pricing (see below).
- `state.py` — `apply_stripe_subscription_state`, the single function that turns a Stripe Subscription object into `HomeSubscription` state (see "Activation rule" and "Out-of-order events" below). Called by both the webhook handler and the manual reconciliation action — one mapping, one place.
- `checkout.py` — Customer get-or-create, Checkout Session creation, Customer Portal session creation.
- `webhooks.py` — signature verification and event dispatch.
- `reconciliation.py` — re-fetches the current Stripe Subscription and re-applies it through `state.py`.

### Stripe Customer mapping

One Stripe Customer per Home, stored on `HomeSubscription.external_customer_id` (now a **unique** column — Phase 1 left it merely indexed; Phase 3's migration tightens it, since one Stripe Customer must never attach to two Homes). `get_or_create_customer` (`checkout.py`) reuses the existing customer on every subsequent Checkout attempt rather than creating a new one. The Stripe Customer's `metadata` carries exactly one non-sensitive identifier, `mykhaya_group_id` — no complimentary reason, no internal notes, nothing beyond what's needed to reconcile a Stripe object back to a Home. `billing_owner_user_id` is set to whichever user actually starts Checkout (informational — see "Billing owner" below); changing it later would not change who owns the subscription, which remains the Home.

### Billing owner permission

`Capability.billing_manage` (new, `mykhaya/household_permissions.py`) gates Checkout/Portal creation — granted only to `home_admin` (`ALL_CAPABILITIES`), matching `household.manage`/`features.manage`'s existing precedent, and deliberately **not** granted to `standard_partner`. An ordinary Home member is not trusted with payment-method management just by belonging to the Home; billing stays with whoever administers it. `billing_owner_user_id` on `HomeSubscription` is purely informational (who started Checkout) — it confers no extra permission and changing it would not transfer commercial ownership, which is always the Home's.

### Product/Price mapping and dynamic pricing

Monthly and annual are two billing intervals of one `family` plan, never two plans — `BillingInterval` (`month`/`year`) lives on `HomeSubscription`, `SubscriptionPlan` is untouched. `mykhaya.billing.pricing.get_family_pricing` reads both configured Price IDs from Stripe at request time (`GET /billing/pricing`, public, rate-limited) and validates each one is active, recurring, and matches the expected interval — a misconfigured Price fails the request clearly (`StripePriceConfigurationError`) rather than silently showing a wrong or stale amount. **No monetary amount is ever hard-coded** — not in entitlement logic, not in frontend components, not in a migration; `MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID`/`_ANNUAL_PRICE_ID` are the only configuration, and the actual amount always comes from Stripe's response. Results are cached in-process for 5 minutes (no existing Redis-backed generic cache convention to reuse — see `mykhaya/billing/pricing.py`'s module docstring) so a page render never costs a Stripe round trip, while a changed Price becomes visible within minutes without a code or migration change.

### Price increases and grandfathering

`HomeSubscription.external_price_id` records the exact Stripe Price a subscription is actually billed against — populated only from the Stripe Subscription object itself (`state.py`), never from `Settings.stripe_family_*_price_id`. Changing the configured Price IDs only affects **new** Checkout Sessions; every existing subscriber keeps whatever price they already have, indefinitely, until Stripe itself changes their subscription. The Platform Control Centre subscription detail view resolves and displays a Home's actual price via `mykhaya.billing.pricing.fetch_price_amount(price_id)` — deliberately unvalidated against "is this the currently configured signup price," since it may legitimately be an old, grandfathered one.

### Checkout lifecycle

`POST /groups/{id}/billing/checkout-session` accepts only `{interval: "month" | "year"}` (`CheckoutSessionRequest`, a `StrictModel` — no Price ID, amount, currency, Customer, or subscription identifier can be supplied). The backend resolves the Price ID from settings, gets-or-creates the Stripe Customer, and creates a subscription-mode Checkout Session with `client_reference_id` and `metadata.mykhaya_group_id` both set to the Home ID (redundant on purpose, for webhook reconciliation), a Stripe idempotency key bucketed to 5 minutes, and success/cancel URLs built from `Settings.public_web_url` (never a client-supplied header).

**Checkout completion is not activation.** `checkout.session.completed` only records the Customer/Subscription IDs onto `HomeSubscription` for reconciliation bookkeeping — it never grants Family. The success redirect (`/settings/billing?checkout=success`) shows "Payment received. We're confirming your subscription." and nothing more; refreshing it, replaying it, or guessing a session ID changes nothing. **Activation rule**: Family is only granted once Stripe itself reports a confirmed billing status — the mapped `SubscriptionStatus` is `active` or `trialing` (i.e. in `mykhaya.entitlements._PLAN_HONOURED_STATUSES`) — via `customer.subscription.created`/`updated`. A Stripe `incomplete` status (first payment not yet confirmed) produces no mutation at all.

### Webhooks

`POST /billing/stripe/webhook` — deliberately **not** under `mykhaya.routers.platform`, since it must be reachable without the admin-subdomain/admin-network restrictions that gate the Platform Control Centre; Stripe calls it directly from Stripe's own infrastructure. Its only trust mechanism is Stripe's cryptographic signature (`stripe.Webhook.construct_event` against the **raw** request body and `Settings.stripe_webhook_secret`) — there is no IP allowlist, and no ordinary authenticated API path can substitute for it. An invalid signature is rejected (400) before any database work happens.

Handled events (deliberately minimal — see `mykhaya.billing.webhooks._HANDLED_EVENT_TYPES`): `checkout.session.completed`, `customer.subscription.created`/`updated`/`deleted`, `invoice.payment_succeeded`/`payment_failed`. Anything else Stripe sends is acknowledged (200) and recorded with outcome `"ignored"` — never a hard failure, since an unrecognised-but-valid event is not an error on MyKhaya's part.

**Idempotency**: `StripeWebhookEvent.stripe_event_id` is unique, and the row is inserted in the *same* transaction as any resulting `HomeSubscription` mutation, committed together. A duplicate delivery is detected (with a lock-protected re-check to close the race between the first check and acquiring the per-Home advisory lock) before any mutation is attempted, and short-circuits to the previously-recorded outcome. A genuine processing **failure** deliberately does not commit the dedup row — the whole transaction rolls back and the route returns 5xx, so Stripe's automatic retry can succeed later rather than the event being silently and permanently dropped. This is a durable, transactional guarantee, not an in-memory cache.

**Group resolution**: most events carry `metadata.mykhaya_group_id`/`client_reference_id` directly (set by MyKhaya at Checkout time). Invoice events don't, so `_resolve_group_id` falls back to looking the Home up by whichever Stripe identifier the payload *does* carry (`subscription`/`customer`), matched against the already-unique `HomeSubscription.external_subscription_id`/`external_customer_id`.

### Out-of-order events

Stripe does not guarantee webhook delivery order. `apply_stripe_subscription_state` always applies the Stripe object's **current full state**, never a delta, which is inherently idempotent for repeated delivery of the same object — the remaining risk is two *different* deliveries genuinely racing. Two guards handle this:

1. An event for a subscription ID that differs from the one currently tracked (while the tracked one hasn't itself ended) is ignored — a stale event for a superseded subscription must never override newer known state.
2. For the *same* subscription ID, `current_period_end` only ever advances forward until cancellation; an incoming event with an *older* `current_period_end` than what's already stored is ignored as stale (cancellation events are exempt from this specific check, since a cancellation's period end is not expected to be later than the last renewal's).

`invoice.payment_succeeded`/`payment_failed` additionally **refetch the current Stripe Subscription object** (`stripe.Subscription.retrieve`) rather than trusting the invoice payload's own snapshot — the most out-of-order-prone pair of events, since invoice and subscription events for the same billing cycle can arrive in either order.

### Activation rules: Stripe status mapping

`mykhaya.billing.state.map_stripe_subscription_status` — an explicit table, never a blind copy of Stripe's status string:

| Stripe status | MyKhaya `SubscriptionStatus` |
|---|---|
| `active` | `active` |
| `trialing` | `trialing` |
| `past_due` | `past_due` |
| `unpaid` | `past_due` (still within grace) |
| `paused` | `past_due` (billing paused, not cancelled) |
| `canceled` | `cancelled` |
| `incomplete_expired` | `cancelled` |
| `incomplete` | *(no mutation — not yet confirmed)* |
| anything unrecognised | *(no mutation — fail safe)* |

`active`/`trialing` are downgraded to `cancel_at_period_end` when Stripe's own `cancel_at_period_end` flag is set — MyKhaya represents that as a status value (already present, unused, since Phase 1) rather than a second boolean column.

### `past_due` and dunning

Phase 1 left `past_due` in `_PLAN_HONOURED_STATUSES` because there was no payment provider yet to have a dunning policy about. **Phase 3's explicit decision: this stays exactly as it was.** A single missed payment never triggers an instant downgrade — Family access is retained, the customer can fix their payment method via the Stripe Customer Portal, and Stripe's own Smart Retries handle reattempting payment. MyKhaya runs no second, competing downgrade timer of its own; it only reacts to the terminal outcome (`customer.subscription.deleted` → `cancelled`, which the entitlement service already treats as not-honoured). This is a deliberate choice to lean on Stripe's own retry schedule rather than duplicate it, not an oversight.

### Cancellation

`cancel_at_period_end` (Stripe flag set, subscription still `active`/`trialing`) and full termination (`customer.subscription.deleted`) are distinct MyKhaya statuses. A Home scheduled to cancel keeps Family access — `cancel_at_period_end` is in `_PLAN_HONOURED_STATUSES` — until the subscription genuinely ends. On genuine termination, `HomeSubscription` is **not** reset to `plan=free, provider=free` the way a Complimentary revoke is — `plan` stays `family`, `provider` stays `stripe`, only `status` becomes `cancelled`. The entitlement service already resolves effective Free for any non-honoured status regardless of what `plan`/`provider` say, so this loses no safety while preserving more history ("this Home *was* a Stripe Family subscriber, now cancelled" — useful for support and reconciliation) than a full reset would. No Home data is ever deleted by any cancellation path.

### Complimentary ↔ Stripe transitions

**Complimentary → Stripe**: Checkout may be started while complimentary access exists (no blocking) — a Home mid-beta can subscribe for real without losing access in between. Once Stripe activation is confirmed, `apply_stripe_subscription_state` flips `provider` to `stripe` and clears the live `complimentary_reason`/`complimentary_note`/`complimentary_expires_at` fields (they'd otherwise sit stale and misleading once Stripe is authoritative) while `complimentary_granted_by`/`complimentary_granted_at` are left as history. The transition itself is recorded as a `HomeSubscriptionEvent` (`from_provider=complimentary, to_provider=stripe`) — nothing is silently discarded, it just stops being the live driver.

**Stripe → Complimentary**: `grant_complimentary` (Phase 1/2 endpoint, unchanged otherwise) now rejects with 409 if the Home's `provider == stripe` and `status != cancelled` — an operator cannot accidentally grant Complimentary access to a Home that's still being actively billed by Stripe. The Stripe subscription must be genuinely cancelled first (via the Portal or Stripe directly); the Platform Control Centre UI shows this as an explicit warning rather than a generic failed request.

### Reconciliation

`mykhaya.billing.reconciliation.reconcile_home_subscription` answers "what does Stripe currently say this Home's subscription state is?" by fetching the live Stripe Subscription and applying it through the *exact same* `apply_stripe_subscription_state` webhooks use — there is no separate repair-specific mutation path. Exposed as `POST /platform/homes/{id}/subscription/reconcile-stripe` (Platform Control Centre, `OPERATORS` only, `require_recent_auth`), audited via both `platform_audit` (`home.subscription_reconciled`) and a `HomeSubscriptionEvent` with `actor_administrator_id` set (the only case where a Stripe-driven transition has a human actor — webhook-driven ones always have `actor_administrator_id=None`). 409s if the Home has no `external_subscription_id` to reconcile against.

### Webhook event storage

`StripeWebhookEvent` stores only what's needed to deduplicate and troubleshoot: the Stripe event ID (unique), event type, resolved Home ID, received/processed timestamps, an outcome (`processed`/`ignored`/`failed`), and a sanitised error message — never the full webhook payload, never anything payment-related.

### Test mode / live mode safety

`Settings.validate_stripe_configuration` rejects a live-mode secret key (`sk_live_...`) outside `MYKHAYA_ENVIRONMENT=production`, and a test-mode key (`sk_test_...`) inside it — both directions, since "wrong environment" is the actual risk. The Platform Control Centre's "Open in Stripe" dashboard links are built with a `/test/` path prefix whenever the configured key is `sk_test_...`, so a test-mode deployment never links to the live dashboard by accident (or vice versa). See docs/operations/dev-deployment.md#stripe-sandbox for the full local setup, including Stripe CLI webhook forwarding, and #going-live for what changes (not performed in Phase 3) when a later phase turns live billing on.

### Explicitly out of scope for Phase 3

No production/live Stripe activation. No hard-coded monetary pricing anywhere. No public homepage pricing cards. No polished signup plan-selection UI. No full household Plan & Billing page (`/settings/billing` was a deliberately minimal test/development surface in Phase 3 — Phase 4, below, replaces it). No Apple/Google billing. No promotional codes. No new commercial tiers. No destructive downgrade cleanup. No MRR/ARR (see `SubscriptionSummaryResponse`'s docstring for why — multiple historical Prices/currencies/intervals make a single blended figure non-trivial to compute correctly, so it's deferred rather than approximated).

## Phase 4: household Plan & Billing

Phase 4 replaces Phase 3's minimal `/settings/billing` test surface with the polished, authenticated household experience — still no public pricing page, still no signup payment step (both remain later phases). It adds no new commercial write path: every state change still flows through Checkout → verified webhook → Family, or the existing Portal/Complimentary flows from Phases 1–3.

### Household Plan & Billing read model

`GET /groups/{id}/billing` (`BillingStatusResponse`, `mykhaya/billing_schemas.py`) is the single backend-prepared, display-safe view the page renders from — the frontend never infers Stripe semantics itself. Extended in Phase 4 beyond Phase 3's minimal shape with:

- `effective_status_reason` — reuses `mykhaya.entitlements.resolve_effective_state`'s human-readable divergence explanation (e.g. "Complimentary access expired"), the same field the Platform Control Centre already showed operators in Phase 2.
- `price` — the Home's own actual current amount, resolved live from Stripe against `HomeSubscription.external_price_id` (via `mykhaya.billing.pricing.fetch_price_amount`, the same function the Platform Control Centre detail view uses) — correctly reflects a grandfathered price, never the current signup price.
- `complimentary_expires_at` — so the page can distinguish "no expiry" from "expires on this date" without the frontend inferring it from other fields.

Deliberately still excludes (unchanged from Phase 3's intent, now made explicit): `complimentary_note` (Platform-Admin-only), any `HomeSubscriptionEvent`/audit history, `StripeWebhookEvent` IDs, raw Stripe Customer/Subscription objects, and any secret. See "Security" below.

### Pricing and plan-comparison consumption

The page reuses Phase 3's public `GET /billing/pricing` unchanged in spirit, with two Phase 4 additions to `FamilyPricingResponse`: `annual_is_best_value` (computed server-side — true only when `annual_saving_unit_amount` is positive, i.e. the current provider prices genuinely make annual cheaper than 12 monthly periods; never a hard-coded assumption) and the removal of `provider_price_id` from the wire response (the frontend never needed it — Checkout only ever sends an interval — so it's no longer sent).

`GET /billing/plans` (new, public, rate-limited like pricing) is the Free vs Family comparison — sourced directly from `mykhaya.entitlements.PLAN_DEFINITIONS`, never hand-duplicated in a frontend file. It deliberately returns only a `calendar.max_calendars` row: `PLAN_DEFINITIONS` also carries `lists.enabled`/`chores.enabled`/`notes.enabled`/`wishlists.enabled`, but none of those correspond to a currently-released module (`mykhaya.module_registry` marks Tasks/Shopping/Meals/Plans/Wish Lists/External sharing all `hidden`) — advertising them as a Family benefit would market features that don't exist yet. This is the `Platform Feature Flag -> Commercial Entitlement -> Home/User Permission` layering applied to marketing copy, not just authorization: an entitlement being technically `True` for Family is not sufficient reason to show it to a customer.

### Checkout handoff (unchanged authority, new UI)

The page still only ever sends `{interval: "month" | "year"}` to `POST /groups/{id}/billing/checkout-session` — no Price ID, amount, currency, or Stripe identifier, exactly as Phase 3 established. What's new in Phase 4 is presentation: two pricing cards (Monthly/Annual) built entirely from `GET /billing/pricing`'s response, a "Best value" badge shown only when `annual_is_best_value` is true (reusing the existing `.release-badge.core` visual treatment — no new badge component), and a busy-state guard preventing a double-submit while a Checkout Session is being created.

### Authoritative webhook/refetch flow (unchanged authority, new UI)

Returning from Stripe still never activates Family by itself. The page reads `?checkout=success`/`?checkout=cancelled` only to decide which banner to show, then always re-fetches `GET /groups/{id}/billing` for the authoritative state (the same request the page makes on every load). If the webhook hasn't landed yet when the page first loads back from Checkout, it schedules exactly **one** additional re-fetch a few seconds later — not continuous polling — and always shows a coherent "still confirming" message rather than flashing between Free and Family while independent requests settle. A manual reload always re-triggers the same authoritative fetch.

### Portal handoff (unchanged authority, new UI)

`POST /groups/{id}/billing/portal-session` is unchanged from Phase 3. The button label switches between "Manage billing" and "Update payment method" purely as frontend copy (`resolvePlanCardKind`/`canShowPortalAction` in `apps/web/components/billing-logic.ts`) depending on whether the Home is `past_due` — both labels create an identical fresh Portal session server-side; there is no separate "payment method update" backend action. No Portal URL is ever stored or reused — a fresh session is created on every click.

### Provider vs entitlement separation (reaffirmed)

Nothing in the Phase 4 frontend calls `has_entitlement`/`effective_plan` itself, and nothing asks Stripe anything — the page only ever reads the single `BillingStatusResponse`/`FamilyPricingResponse`/`PlanComparisonResponse` shapes the backend already resolved. This keeps the same layering Phase 1 established intact through the customer-facing surface, not just the admin one.

### Explicitly out of scope for Phase 4

No public homepage pricing cards. No signup/onboarding plan selection or payment requirement. No custom card-entry form (Stripe Checkout/Portal handle all payment-method UI). No local invoice/billing-history UI beyond pointing at "Manage billing" (Stripe's Portal already provides this). No Apple/Google billing. No promotional codes. No MRR/ARR. No new commercial tiers. No destructive downgrade behaviour beyond what Phases 1–3 already established.

## Phase 5: public pricing and signup/onboarding

Phase 5 adds the pre-login commercial journey — a pricing section on the public homepage and a plan-selection step in signup/onboarding. It introduces **no new backend endpoint and no schema change**: it is entirely a new UI in front of endpoints that already existed and were already public (`GET /billing/pricing`, `GET /billing/plans`, both introduced/extended in Phases 3–4 and already documented above as safe to leave unauthenticated) plus the existing registration (`POST /auth/register`), Home creation (`POST /groups`), and Checkout (`POST /groups/{id}/billing/checkout-session`) endpoints, used in their existing established order.

### Public pricing endpoint (reused, not new)

`apps/web/components/public-pricing.tsx` (rendered from the homepage, `apps/web/app/page.tsx`) and the plan step of `apps/web/app/onboarding/page.tsx` both call `api.familyPricing()` / `api.planComparison()` — the exact same client methods, hitting the exact same `GET /billing/pricing` / `GET /billing/plans` endpoints, that Settings → Plan & Billing (Phase 4) already uses. There is one pricing computation (`mykhaya.billing.pricing.get_family_pricing`, one bounded in-process cache) feeding every surface — public, signup, and authenticated — so there is no second amount calculation to drift out of sync. `test_signup_commercial_intent.py::test_public_pricing_is_identical_whether_or_not_the_caller_is_signed_in` asserts this directly: an anonymous and a signed-in caller get byte-identical JSON for the same configured Stripe prices.

### Signup commercial-intent handling

The public pricing section's "Choose Family" CTA carries the visitor's selection into `/register` as `?plan=family&interval=month|year` — this is the *only* place a plan value ever appears in a URL, and it is read back through `parseIntentFromParams` (`apps/web/components/onboarding-intent.ts`), which maps anything outside the closed `{free, family}` / `{month, year}` enums to the safe default rather than trusting it. Neither `RegisterRequest` nor `GroupCreate` (the request schemas behind `POST /auth/register` and `POST /groups`) accept a plan/provider/status field at all — both are `StrictModel` (`extra="forbid"`), so any attempt to smuggle commercial state into either request is rejected with `422` before any handler code runs; `test_signup_commercial_intent.py` proves this for both endpoints. The query-string value is never sent to either endpoint — it only ever (a) pre-fills a confirmation line on `/register` and (b) is opportunistically saved to `localStorage` (`saveOnboardingIntent`, capped at 48 hours, cleared once acted on) purely so the plan step later in onboarding can pre-select what the visitor picked. If that value is lost — private browsing, a different device, an expired window — onboarding simply falls back to presenting the same Free/Family choice with Free preselected; nothing about correctness depends on the hint surviving.

### Account/Home creation before Checkout

The order is fixed and unconditional: `POST /auth/register` creates the `User`/`AuthIdentity` only; `POST /groups` (reached only after login, from `/onboarding`) creates the `Group` and, via the existing `ensure_home_subscription`, the Free/free/active `HomeSubscription` row — this happens identically regardless of which plan was selected on the homepage. Only *after* the Home exists as Free does the onboarding plan step optionally call the existing `POST /groups/{id}/billing/checkout-session` (Family path) — the same endpoint, same `{interval}`-only body, same `billing_manage` capability gate Phase 3 built. `test_signup_commercial_intent.py::test_new_home_is_always_free_regardless_of_query_string` proves a Home created with `?plan=family&interval=year` on the request URL is still created Free/free/active — the query string never reaches the handler's decision at all, it isn't even read there.

### Authoritative webhook activation (unchanged)

Nothing about Phase 5 changes how Family is ever actually granted: Stripe's verified webhook, via the same `apply_stripe_subscription_state` every other phase uses, remains the only path. A visitor who abandons Checkout, whose payment fails, or who returns while the webhook is still in flight keeps a fully valid account and a fully valid Free Home — there is no partial/orphaned state to clean up, because the account and Home were never conditional on Checkout completing. Returning from Checkout is handled by the same Phase 4 "confirm, then re-fetch once" flow (`apps/web/app/settings/billing/page.tsx`) once the visitor is inside the app; the onboarding plan step itself does not attempt to interpret a Checkout redirect, since Checkout only ever begins there, it doesn't return there (Stripe's success/cancel URLs point at `/settings/billing`, unchanged from Phase 4).

### Invite-path exclusion

An invited member never sees a plan choice, by construction rather than by an added check: they register via the same `/auth/register` (with `invitation_token` set), but then join the *existing* Home via `POST /invitations/accept` from `/login` — a path that never touches `POST /groups` and therefore never reaches `/onboarding`'s plan step at all. `apps/web/app/register/page.tsx` additionally suppresses reading `?plan=`/`?interval=` entirely whenever an `invitation` token is present, so even a crafted invite link carrying a plan query string has no effect. `test_signup_commercial_intent.py::test_invited_member_joins_existing_home_without_a_new_home_or_plan_choice` asserts the joined Home's commercial state is byte-for-byte unchanged by the invitee's registration and acceptance.

### Existing-account routing

The public pricing CTAs check auth state on click (`api.me()`, then `api.homes()` if signed in) before deciding where to go (`resolveCtaDestination`, `apps/web/components/cta-destination.ts`): an anonymous visitor goes to `/register` with their intent; a signed-in visitor with no Home yet goes to `/onboarding` (same page anyone freshly registered reaches); a signed-in visitor who already has a Home is **always** routed to an authenticated destination (`/settings/billing` for the Family CTA, `/home` for the Free CTA) and never back through `/register` or a second `POST .../checkout-session` call. Because the Family CTA always lands on the existing Settings → Plan & Billing page rather than starting a new Checkout itself, Phase 4's existing duplicate-subscription protection and Complimentary-state display are reused as-is — Phase 5 adds no new "is this Home already paying" logic of its own.

### Consistency and no duplicate calculation

`apps/web/components/family-pricing-logic.ts` (`pricingOptionFor`, `isBestValueInterval`, `savingLabelFor`) is the one place the public/signup surfaces read a `FamilyPricing` response; it performs no calculation of its own beyond looking up fields the backend already computed. `intervalName`/`intervalSuffix` are imported from Phase 4's `billing-logic.ts` rather than re-declared. No currency string is assumed anywhere in this code — every displayed amount is `formatted_amount` as returned by the pricing service, and "Save £X per year" only ever renders the backend's own `annual_saving_formatted`.

### SEO / rendering tradeoff

The homepage (`apps/web/app/page.tsx`) remains a plain server component — hero, nav and copy are still fully server-rendered with no data dependency. The pricing section is a client-side "island" (`PublicPricing`, `"use client"`) that fetches on mount, rather than a server-side fetch of live Stripe-derived pricing at request time. This repo has no existing pattern for a Server Component issuing an authenticated/backend fetch (the API client's relative `/api/v1/...` base URL relies on a browser-only cookie/CSRF flow and Next's `rewrites()`, which only applies to inbound requests, not outbound `fetch` calls made during server rendering) — introducing one would be a new architectural mechanism disproportionate to this phase. The tradeoff: pricing amounts are not present in the initial HTML for crawlers, but the rest of the homepage (which is what search engines actually index for intent/positioning) is unaffected, loads instantly, and never blocks on Stripe being reachable.

### Explicitly out of scope for Phase 5

No Apple/Google billing. No promotional codes/discount UI. No new commercial tiers. No custom card-entry form. No destructive downgrade enforcement. No MRR/ARR. No referral/affiliate programmes. No broad public-site redesign beyond the pricing section. No live Stripe activation.
