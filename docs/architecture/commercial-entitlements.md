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

Phase 1 defined `calendar.max_calendars` (`1` for Free, unlimited for Family) as plan data only — `require_within_limit` had no live caller, because no endpoint could create a second calendar. **Phase 6 is where this becomes real enforcement** — see "Phase 6: feature entitlement enforcement and safe downgrades" below for the full implementation.

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

- `config.py` — `resolve_stripe_config(settings, db) -> StripeConfig` (`source: "database" | "environment" | "unconfigured"`, `configured: bool`, `mode: "test" | "live"`, `incomplete_reason: str | None`). Stripe credentials, unlike the acquisition kill switch below, are Platform-Admin-manageable through the Control Centre's Payments page (`PlatformStripeSettings`, single row, Test and Live credentials in separate columns, secret/webhook values encrypted at rest via `mykhaya.secrets_crypto`) — see "Stripe configuration precedence" in `docs/architecture/platform-control-centre.md`. **The database row, once enabled, takes precedence over the `MYKHAYA_STRIPE_*` environment variables** — the reverse of SMTP/push's env-wins precedence — and an incomplete active-mode configuration never falls back to the environment or to the other mode, so Live can never silently run on Test credentials. `Settings.validate_stripe_configuration` (in `mykhaya/config.py`) still refuses to *boot* with a half-configured `MYKHAYA_STRIPE_BILLING_CONFIGURED=true` environment fallback, and rejects a live key outside production or a test key inside it; the equivalent check for the database path happens per-request in `resolve_stripe_config`, since an incomplete admin-entered row is a runtime, repairable admin state, not a startup failure.
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

## Phase 6: feature entitlement enforcement and safe downgrades

Phases 1–5 built the commercial model, its administration, its billing provider, and its customer-facing surfaces — but nothing in the product itself actually *changed behaviour* based on plan. Phase 6 closes that gap using Calendar as the first real implementation, and establishes the pattern every future module should follow.

### The three-layer authorization order

Every protected calendar action checks, in this order:

```
Platform Feature Flag  (mykhaya.features.require_feature)
        ↓
Commercial Entitlement (mykhaya.entitlements — has_entitlement / require_within_limit)
        ↓
Home/User Permission   (mykhaya.household_permissions.require_capability)
        ↓
Allow
```

`routers.calendar`'s router-level `require_calendar_feature` dependency (unchanged from earlier phases) enforces the feature-flag layer for every route on the router before any handler runs. Each calendar-management/event handler then calls `require_capability` (permission) and, for calendar creation, `require_within_limit` (entitlement) — independently. A Family subscription never grants a permission a user doesn't otherwise have (`test_family_entitlement_does_not_grant_permission_to_an_unauthorised_member`); a Home Admin's full permission never bypasses a commercial limit (`test_free_home_admin_still_cannot_exceed_the_limit`); a disabled feature flag blocks access even on Family (`test_disabled_calendar_feature_blocks_access_even_on_family`). All three tests live in `apps/api/tests/test_calendar_entitlements.py`.

### What counts toward `calendar.max_calendars`

Only real `HomeCalendar` rows. Investigation (this phase) confirmed birthdays and household routines are synthesized views computed from `ChildProfile`/`User`/routine data at read time — they never materialize as `HomeCalendar` or `CalendarEvent` rows, so they structurally cannot inflate the count. No filtering logic was needed to exclude "system" calendars because none exist.

### The calendar-management endpoints

`HomeCalendar` already had an `is_primary` column and a `(group_id, is_primary)` uniqueness invariant from Phase 1's schema (migration `0003_calendar_module`) — but that was a full `UniqueConstraint`, which also (accidentally) capped a Home at exactly one *non-primary* calendar. Migration `0022_multi_calendar_entitlement` replaces it with a partial unique index (`WHERE is_primary`) that keeps "exactly one primary calendar per Home" while allowing any number of secondary ones. No other schema change was needed — no `is_paid_locked` flag, no second Subscription table; commercial access is derived fresh on every read (see below), never persisted.

New endpoints on the existing `routers.calendar` router (same feature-flag gate, same `Capability.calendar_edit_all` a calendar/category label creation already uses — a calendar is shared household structure, not personal content):

- `GET /homes/{home_id}/calendars` — every calendar plus its `commercial_access` (`"normal"` / `"read_only_due_to_plan"`) and the Home's current limit.
- `POST /homes/{home_id}/calendars` — creates a secondary (`is_primary=False`) calendar, enforcing the limit (below).
- `DELETE /homes/{home_id}/calendars/{id}` — deletes a non-primary calendar (and, via `CalendarEvent.calendar_id`'s existing `ondelete=CASCADE`, its events). The primary calendar can never be deleted (`409`). This is the customer's own voluntary way to reduce usage back within a Free limit — see "Reducing usage" below.

`EventCreate` gained an optional `calendar_id` (defaults to the primary calendar, exactly matching pre-Phase-6 behaviour when omitted) so a Family Home can actually target its additional calendars. `EventOccurrence` gained `calendar_id` in its response for the same reason. No other event-response field, and no change to `list_events`, month/week/day/agenda rendering, recurrence, reminders, or notifications — see "Why event views needed no changes" below.

### Race-safe limit enforcement

`create_calendar` acquires `SELECT pg_advisory_xact_lock(hashtext('calendar:{home_id}'))` — the identical pattern `routers.billing.checkout_session` already uses to serialize concurrent Checkout attempts per Home — before counting existing calendars and calling `require_within_limit` within the same transaction. `test_concurrent_calendar_creation_cannot_exceed_the_limit` demonstrates this with genuine concurrent requests (`asyncio.gather`) against the real test database: since Free/Family only offer limits of `1` or unlimited (neither has an observable race window on its own — Free starts already at its limit, Family has none), the test temporarily widens Free's limit to `3` via `monkeypatch.setitem` on `PLAN_DEFINITIONS`, fires 5 concurrent creation requests when only 1 slot remains, and asserts exactly one succeeds and the Home never ends up with more than 3 calendars.

### The reusable pattern: `classify_ordered_resources`

`mykhaya.entitlements.classify_ordered_resources(ordered_ids, limit)` is a small, pure, generically-reusable function: given resource ids already placed in the caller's own deterministic priority order, it returns which ones fall within `limit`. Calendar is the only caller today, but any future numeric-limited resource (once a second one exists) reuses this instead of re-deriving "first N stay normal." It performs no database access and never mutates anything — `mykhaya.routers.calendar._calendar_access` is the thin, calendar-specific wrapper that supplies the ordering (primary first, then oldest-first) and calls it.

### Choosing the retained Free calendar

The primary calendar always sorts first and can never be deleted (`delete_calendar` returns `409` for it) — so it is always, deterministically, the calendar that stays `"normal"` after a downgrade. No fallback logic for "no valid primary exists" was needed, because that state is unreachable by construction. This was a simpler, safer design than an arbitrary "oldest calendar" rule that could change if a delete were ever allowed to remove the primary.

### Downgrade behaviour: nothing is deleted, excess calendars go read-only

`commercial_access` is **derived, never persisted** — computed fresh on every `GET /calendars`, `POST .../events`, `PATCH .../events/{id}`, and `DELETE .../events/{id}` call from the Home's *current* effective entitlement and *current* calendar count. A downgrade (Stripe ending, Complimentary expiring/being revoked, or any future transition) never deletes a `HomeCalendar` or `CalendarEvent` row — it just changes what `classify_ordered_resources` returns the next time it's asked. Concretely, for a Family Home with calendars A (primary), B, C that becomes effectively Free (limit 1):

- All three `HomeCalendar` rows, and every event in them, remain in the database untouched.
- A is `"normal"` — full create/edit/delete, exactly as a plain Free Home's only calendar already works.
- B and C are `"read_only_due_to_plan"` — still fully **viewable** (their events remain in `GET /events` results exactly as before, since that endpoint filters by `group_id`, not `calendar_id` — see "Why event views needed no changes"), but `create_event`/`update_event`/`delete_event` targeting them return `403 resource_restricted_by_plan`.
- Creating a fourth calendar is blocked (`403 plan_limit_reached`), same as a plain Free Home.
- The customer can still `DELETE` B or C outright (a deliberate, confirmed action — `HomeCalendarDeleteRequest` requires `confirmed: true`, matching the existing child-removal/relationship-change confirmation convention) to voluntarily reduce usage.

### Re-upgrade and reducing usage both "just work"

Because nothing is persisted, there is nothing to restore. The moment the Home's effective plan resolves back to Family (Stripe reactivation, a new Complimentary grant, any future path), `classify_ordered_resources` returns `"normal"` for every calendar on the very next read — no migration, no backfill, no support action, no stale flag to clear. The same is true in the other direction: if a customer manually deletes calendars until the Home is back within its Free limit, the remaining calendar(s) are `"normal"` immediately, for the same reason. `test_reupgrade_restores_full_access_to_preserved_calendars` and the voluntary-delete assertion inside `test_downgrade_preserves_all_calendars_and_restricts_the_excess_ones` cover both directions.

### Why event views needed no changes

`list_events` (and therefore every month/week/day/agenda rendering built on it) already filters by `CalendarEvent.group_id`, not `calendar_id` — it has always returned every event for the Home regardless of which calendar owns it. This meant Phase 6 could satisfy "prefer preserving visibility" (events in a read-only-due-to-plan calendar remain visible everywhere they always were) and "a restricted event must not be editable in one view but not another" (the restriction is enforced once, server-side, in `create_event`/`update_event`/`delete_event` — never per-view) **without touching the view layer at all**. This was a deliberate scope decision: rather than building a calendar-switcher UI that filters which events render, the existing unified view was left exactly as it was, and only the mutation endpoints gained the check. Reminders, notifications, recurrence, multi-day events, participants, and invitations are all untouched code paths, so none of them needed re-verification against this phase's changes.

### The structured commercial-restriction error

Every other error response in this codebase is `HTTPException(status_code, detail="<sentence>")` with `detail` as a plain string — that convention is preserved everywhere it already existed. Phase 6 adds one new, additive shape for commercial restrictions specifically: `mykhaya.entitlements.commercial_restriction_error(code, message, **metadata)` builds `HTTPException(403, detail={"code": ..., "message": ..., **metadata})`. Three stable, provider-neutral codes:

- `plan_feature_unavailable` — a boolean entitlement is off for this plan (`require_entitlement`, still uncalled by any live module, updated for when one exists).
- `plan_limit_reached` — a numeric limit has been hit trying to create a new resource (`require_within_limit`; metadata: `entitlement`, `limit`).
- `resource_restricted_by_plan` — an *existing* over-limit resource can't be mutated (Calendar's `_require_calendar_writable`; metadata: `entitlement`).

`packages/api-client`'s `request()` was extended additively: a string `detail` behaves exactly as before (every existing caller across the whole app is unaffected); an object `detail` with a `message` field populates `ApiError.message` from it and additionally exposes `ApiError.code`/`ApiError.metadata`, so frontend code can branch on `code` without parsing message text. `metadata` is always safe, provider-neutral context (an entitlement key, a numeric limit) — never a Stripe status, a Complimentary reason/note, or an internal ID.

### Future module enforcement standard

For a boolean entitlement:

```python
await require_entitlement(db, home_id, "lists.enabled")
```

For a numeric resource limit, inside one transaction:

```python
await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"<module>:{home_id}"})
count = await db.scalar(select(func.count()).select_from(Model).where(Model.group_id == home_id))
await require_within_limit(db, home_id, "<module>.max_x", count or 0)
# ... insert, same transaction, commit
```

For deriving which of several existing resources stay fully usable after a downgrade:

```python
ordered_ids = [...]  # caller's own deterministic priority order
limit = await get_limit(db, home_id, "<module>.max_x")
access = classify_ordered_resources(ordered_ids, limit)  # {id: True/False}
```

Every check stays three independent layers (feature flag → entitlement → permission) — never merge them, never branch on `subscription.provider`/`subscription.status` outside `mykhaya.entitlements` itself. Raise through `commercial_restriction_error` with one of the three standard codes rather than a bespoke shape. No module needs to invent its own upgrade UX — reuse `apps/web/components/calendar-entitlement-logic.ts`'s pattern (or extract it further once a second module needs it) and link to `/settings/billing`, which already owns pricing display.

### Diagnostics: Platform Control Centre and household Plan & Billing

Both surfaces call the same new `mykhaya.entitlements.calendar_usage(db, home_id)` helper (one `COUNT(*)` plus the existing `get_limit`) so they can never disagree:

- Platform Control Centre's `GET /platform/subscriptions/{id}` gained `calendar_usage` (`count`, `limit`, `over_limit`) in `SubscriptionDetailResponse`, shown as a read-only diagnostic line ("Current calendars: 3, Over plan limit") next to the existing entitlements block. No unlock action was added — an operator's only way to change what a Home is entitled to remains the existing Complimentary grant/revoke or a real Stripe change, exactly as before.
- The household `GET /groups/{id}/billing` (`BillingStatusResponse`) gained the same `calendar_usage` field; Settings → Plan & Billing shows an explanatory notice only when `over_limit` is true ("Your Home has 3 calendars. The Free plan includes 1. Your calendars and events are safe. Upgrade to Family to restore full access to all calendars.") — never a warning for a Home that's simply on Free within its limit, and never a hard-coded price (the existing pricing cards below it already own that).

### No forced payment, no security-function restriction

Nothing in Phase 6 blocks login, MFA, password change, security settings, account deletion, or access to the Home itself — commercial enforcement is scoped entirely to the calendar-creation/-mutation endpoints. An over-limit Home can still sign in, view every calendar (including restricted ones), manage its account, and reach Plan & Billing to resolve the situation, exactly per "No restrictions on security/account functions."

### Performance

`_calendar_access` resolves the Home's entitlement and calendar list once per request and reuses the resulting map — never once per calendar or per event. No Stripe call happens anywhere in the calendar-enforcement path; entitlement resolution is entirely local (`mykhaya.entitlements`), consistent with every earlier phase's provider-abstraction rule.

### Hidden modules: investigated, not enabled

Lists, Chores, Notes and Wish Lists remain `ReleaseState.hidden` in `mykhaya.module_registry` — Phase 6 added no navigation, no placeholder screens, and did not turn them on. Investigation found no live backend route for any of the four (no `routers/lists.py`, `routers/chores.py`, etc. exist) — their `*.enabled` booleans in `PLAN_DEFINITIONS` remain data only, with nothing to enforce against, exactly as Phase 1 left them. There is therefore no "backend functionality reachable despite being hidden in the frontend" gap to close for these four modules.

### Explicitly out of scope for Phase 6

No Apple/Google billing. No live Stripe activation (still Phase 7). No promotional codes. No MRR/ARR. No new commercial tiers. No enabling of Lists/Chores/Notes/Wish Lists. No destructive data cleanup of any kind. No per-Home entitlement overrides outside the existing Complimentary mechanism. No calendar rename/move-events/participant-management UI beyond what already existed on events themselves.

## Phase 7: production billing readiness

Phase 7 introduces no new commercial feature — it hardens and operationalises the system Phases 1–6 already built, so it can eventually accept real payment safely. **It does not itself enable live billing.**

### The billing acquisition gate

Two previously-conflated ideas are now separate flags:

```
Stripe configured (MYKHAYA_STRIPE_BILLING_CONFIGURED)
        ≠
New paid acquisition enabled (MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED)
```

`mykhaya.billing.config.StripeConfig.acquisition_enabled` is the one flag `routers.billing.checkout_session` checks (after capability and configuration checks, before ever calling Stripe) — disabled, it returns `503 "New Family sign-ups are temporarily unavailable."` and does nothing else. Nothing else is gated by it:

- **Free signup and Home creation** — unaffected; never touch Stripe config at all.
- **Existing Stripe-backed Homes** — unaffected; `HomeSubscription` rows and entitlement resolution don't consult this flag.
- **Webhook processing** — unaffected; `POST /billing/stripe/webhook` has no acquisition check, so renewals, cancellations, and payment-failure events for existing subscribers keep processing regardless (Phase 7's explicit "don't couple `billing_enabled` to `accept_webhooks`" requirement).
- **Customer Portal** — unaffected; a billing manager can always open the Portal for an existing Stripe Customer.
- **Reconciliation** — unaffected.
- **Public pricing (`GET /billing/pricing`)** — stays informational: the real provider-derived price is still returned, plus a new `acquisition_enabled` field the frontend uses to swap "Choose Family" for a "New Family sign-ups are temporarily paused" notice. The price is never hidden or replaced with a stale figure.
- **Household `stripe_billing_available`** (`GET /groups/{id}/billing`) now means "Stripe is configured AND acquisition is enabled" — `canShowUpgradeOptions` on Settings → Plan & Billing already read this field from Phase 4, so the kill switch correctly hides the upgrade section there with zero frontend logic change.

`Settings.validate_stripe_configuration` rejects `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=true` with `MYKHAYA_STRIPE_BILLING_CONFIGURED=false` at startup — acquisition can never be "on" while Stripe itself is half- or un-configured. Both default to `false` everywhere, including production, so **deploying code never itself enables paid acquisition** — a human sets the environment variable as a distinct, deliberate step. See "Deliberate go-live approval" below for why this is deployment configuration, not a Platform Control Centre toggle.

### Reconciliation authority: never trust a mismatched Stripe object

`mykhaya.billing.state.apply_stripe_subscription_state` — the single function both the webhook handler and manual reconciliation funnel through — now validates that a Stripe Subscription object's own `metadata.mykhaya_group_id` (set at Checkout time) agrees with the `group_id` it's being applied to, raising `SubscriptionOwnershipMismatchError` (mapped to `409` in the Platform Control Centre reconciliation endpoint) if they disagree. In practice this should be unreachable today — the webhook path derives `group_id` *from* this same metadata (or from a `HomeSubscription` row already uniquely scoped to the right Home), and reconciliation only ever re-fetches a Subscription ID already on file for that Home — but it's defence-in-depth against a future code path, a data-integrity bug, or an operator error, per "Reconciliation authority" in the security doc.

### Provider-ID uniqueness

`HomeSubscription.external_customer_id` and `external_subscription_id` are both DB-level `unique` columns (established in Phase 3) — a Stripe Customer or Subscription can never resolve to two Homes. `test_a_stripe_customer_id_cannot_resolve_to_two_homes` / `test_a_stripe_subscription_id_cannot_resolve_to_two_homes` (`test_billing_production_readiness.py`) added as regression coverage proving the constraint, not new enforcement.

### Webhook observability

A new `stripe_webhook_failures` table (migration `0023_billing_readiness`) is an **append-only observability log**, deliberately separate from `stripe_webhook_events`: a processing failure is recorded here for operator visibility, while `stripe_webhook_events` — the actual dedup mechanism — still commits nothing for a failed attempt, so Stripe's own retry of that event is never silently swallowed. A retried event that succeeds writes a normal `processed` row to `stripe_webhook_events`, same as if it had succeeded first try. `test_a_processing_failure_is_recorded_without_blocking_retry` proves both halves of this with a genuinely failing payload (a malformed `current_period_end`), not a mocked exception.

`mykhaya.platform_health.current_platform_health` gained a `stripe_webhook` signal (`configured` / `state: not_configured|healthy|warning` / `recent_failure_count` in a trailing 24-hour window / `last_event_at`) alongside the existing SMTP/queue signals, using the exact same pull-based pattern (computed on page load, no push alerting — see "Webhook failure alerting" below for why). Surfaced on the Platform Control Centre overview (a "Stripe webhooks" service-state row, plus an actionable item when degraded) and on a new `GET /platform/subscriptions/webhook-health` endpoint (recent events, recent failures, never the raw Stripe payload). `SubscriptionDetailResponse` also gained `recent_webhook_events` scoped to that one Home, for the "I paid but I'm still on Free" support diagnostic (see "Billing support diagnostics" below).

### Webhook failure alerting

No push/email alerting exists for this, deliberately: `mykhaya.platform_health`'s existing signals (SMTP, queue depth, worker/scheduler heartbeats) are all pull-based — visible when an operator opens Platform Control Centre, never proactively pushed — and Stripe webhook health now follows the identical convention rather than inventing a new mechanism. Building outbound alerting (e.g. emailing Platform Administrators on sustained failure) is a real, reasonable future enhancement, but was out of proportion to add here per "do not build an external monitoring platform solely for Phase 7" — it's noted as a documented gap in the operations runbook, not silently skipped.

### Stale webhook detection

Considered and deliberately rejected: "no webhook received in N days" is not a reliable health signal, because long gaps between real Stripe lifecycle events (a renewal every month or year) are completely normal and would produce constant false alarms. The chosen signal is **failure count** (`recent_failure_count` in the health snapshot above), which only reacts to an actual processing problem, never to the mere absence of activity.

### Failed-event repair

Recovery is Stripe's own retry (automatic, and this is why `stripe_webhook_failures` deliberately never blocks it) plus the existing manual reconciliation action for a specific Home. No generic "replay an arbitrary captured payload" endpoint was built — that would bypass Stripe's own signature trust and was explicitly out of scope. If a specific event needs manual intervention beyond what reconciliation covers, the documented path (see the operations runbook) is inspecting the Stripe Dashboard's own event log and, if needed, having Stripe resend the event.

### Bulk reconciliation

Not built. At current scale a single-Home reconciliation action (already existing since Phase 3) covers the realistic recovery case; a bulk "reconcile every Stripe-backed Home" endpoint would need its own rate-limiting/batching design to avoid a Stripe API storm, and there's no evidence yet that scale requires it. Documented instead as a safe, scripted `psql`-plus-loop-over-the-existing-per-Home-endpoint operational procedure in the operations runbook, so outage recovery is possible without a database write.

### Stripe outage behaviour

Tested directly (`test_existing_family_entitlement_survives_stripe_being_unreachable`, `test_checkout_fails_safely_when_stripe_is_unreachable`):

- **Existing entitlement resolution never calls Stripe.** `mykhaya.entitlements` reads only the local `HomeSubscription` row — proven by monkeypatching every Stripe SDK call MyKhaya makes to raise `AssertionError`, then confirming a Family-only action (creating a second calendar) still succeeds for a Stripe-backed Family Home.
- **New Checkout fails safely.** A Stripe outage during `create_checkout_session` surfaces as `503`, and the Home's stored plan remains exactly what it was (Free stays Free) — never a partial or corrupted state.
- **Never fails open into Family, never fails closed by stripping existing access** — both directions were explicit non-negotiables; the architecture already satisfied both by construction (entitlement resolution is 100% local; Stripe failures only ever block a *new* provider-dependent action).

### Pricing cache and outage

Unchanged from Phase 3's design, reconfirmed here: `mykhaya.billing.pricing`'s in-process cache (5-minute TTL) means a transient Stripe blip within the cache window is invisible to the customer; total unavailability surfaces as the existing `503` with the existing "temporarily unavailable, you can still create a Free account" copy — never a hard-coded fallback amount, never a block on Free registration.

### Least-privilege Stripe credentials

MyKhaya's Stripe usage is narrow: Customers (create/retrieve), Checkout Sessions (create), Customer Portal Sessions (create), Subscriptions (retrieve), Prices (retrieve). All of this is satisfiable by a Stripe **restricted key** scoped to exactly those resources at the permission level actually used (write for Customers/Checkout Sessions/Portal Sessions, read for Subscriptions/Prices) rather than an unrestricted secret key — see the operations runbook's key-rotation section for the recommended restricted-key permission set. This is a recommendation for the live credential, not a code change; MyKhaya makes no assumption about key scope today.

### Deliberate go-live approval

Per Phase 7's explicit instruction not to build a casual remote toggle: `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED` is deployment configuration (an environment variable, restart-required), the same trust model as `MYKHAYA_STRIPE_BILLING_CONFIGURED` and the Stripe secrets themselves — not a Platform Control Centre switch. Platform Control Centre only ever shows the *current* state read-only (via the readiness check — see below); it cannot change it. This keeps the single most consequential commercial action (starting to actually charge real customers) behind the same infrastructure-level access control as rotating a secret, not behind a web session that could be phished, CSRF'd, or misclicked.

### The readiness command

`mykhaya.billing_readiness` (run via `infrastructure/scripts/billing-readiness.sh`) answers "is this deployment correctly configured to enable Stripe billing" without taking payment: configuration completeness, Stripe/environment mode consistency, the acquisition-gate state, and — opt-in via `--check-stripe` — a live (test-mode only; refuses a live key) call confirming the configured Price IDs actually resolve. Prints `PASS`/`WARN`/`BLOCKER` lines, never a secret value, and explicitly does not claim readiness equals "go-live approved" — real Stripe sandbox lifecycle verification and the business/legal decisions (tax/VAT, Terms wording) remain separate, human judgement calls documented in the operations runbook's go-live checklist.

### Explicitly out of scope for Phase 7

No live Stripe activation (this phase prepares for it; a human still flips the switch later, outside this engagement). No Apple/Google billing. No promotional codes. No MRR/ARR. No new commercial tiers. No refund button inside MyKhaya (Stripe Dashboard remains the operational workflow — see the operations runbook). No dispute/chargeback webhook processing (Stripe Dashboard remains authoritative; disputes are not automated). No bulk reconciliation UI (documented scripted procedure instead). No outbound webhook-failure alerting (documented as a future enhancement).

## Commercial plan cleanup

A focused correction pass over `PLAN_DEFINITIONS` and its presentation, done before further Stripe sandbox testing so the commercial model being tested matches the product actually intended for sale. Introduces no new commercial feature layer, no Stripe changes, and no new plan.

### The agreed Free vs Family model

| Capability | Free | Family |
|---|---|---|
| People | 1 person | Whole household |
| Calendar | Included | Included |
| Event categories | 1 category | Unlimited |
| Events | Included | Included |
| Notes | Included | Included |
| Personal routines | Up to 3 | Unlimited |
| Household routines | Not included | Included |
| Shared family events | Not included | Included |
| Lists | Not included | Included |
| Chores | Not included | Included |
| Gift Wishlists | Not included | Included |
| Invite household members | Not included | Included |
| Invite external members | Not included | Included |
| Family Plans | Not included | Included |
| Priority Support | Not included | Included |

This is the authoritative representation — `PLAN_DEFINITIONS` in `mykhaya/entitlements.py`. Product framing: Free is a genuinely useful **single-person personal organiser**; Family is the full **household coordination experience**. See `docs/product/plans-and-pricing.md` for the customer-facing version.

### No redundant duplicate state

"People" and "Invite household members" are the *same* underlying rule (`home.max_members`), presented as two customer-facing rows rather than two entitlement keys — the Platform Control Centre and product docs derive both display strings from the one limit. "Calendar" and "Event categories" are similarly related but genuinely distinct: Calendar is always included on both plans (never entitlement-gated — there's nothing to restrict), while `calendar.max_categories` is the actual numeric differentiator. Neither pairing introduces a second, conflicting source of truth.

### Event categories — renaming `calendar.max_calendars`

The persisted `HomeCalendar` model (Phase 1/6) is used, in practice, as the user-facing grouping for events — an "event category" in product terms, not a second personal calendar. Advertising Free's limit as "1 calendar" was actively misleading (both plans always include the Calendar itself). The commercial entitlement key was renamed:

```
calendar.max_calendars  →  calendar.max_categories
```

every backend caller (`routers/calendar.py`'s `CALENDAR_LIMIT_KEY`, `routers/billing.py`'s plan comparison, `entitlements.calendar_usage`), every test (`test_calendar_entitlements.py`, `test_entitlements.py`, `test_platform_subscriptions_management.py`, `test_billing_plan_page.py`), and every customer/operator-facing label ("Calendar Maximum"/"Current Calendars" → "Event categories"/"Current usage → Event categories") was updated in the same change — a repo-wide search confirmed no stale reference to the old key remains, which matters because `get_limit`'s fail-safe (`unknown key → 0`) means a missed caller would have silently zeroed out Family's calendar entitlement rather than erroring loudly.

**The underlying `HomeCalendar` database model, table name, API routes (`/homes/{id}/calendars`), and frontend route/component/file names (`/calendar/calendars`, `calendar-entitlement-logic.ts`) were deliberately left unchanged** — this is a commercial/domain terminology correction, not a data-model refactor. Only customer-facing copy (badges, error messages, page headings) and the internal commercial key were corrected. Blast radius was assessed as manageable (a small, well-understood set of callers, all already covered by Phase 6's test suite) before proceeding with the rename rather than keeping the misleading key.

### People — `home.max_members`

New numeric entitlement, `1` for Free / `None` (unlimited) for Family. Enforced at the one place a Home's member count actually grows: `POST /invitations` (`routers/invitations.py`) counts active `Membership` rows and calls `require_within_limit`, wrapped in the same per-Home `pg_advisory_xact_lock` pattern Calendar established in Phase 6 (kept for consistency and future-proofing even though today's two-tier limit values — 1 or unlimited — don't create a real race window, since a Free Home's creator already saturates the limit at Home-creation time). **Never evicts an existing member** — a Family Home that invited several people and then downgraded keeps every existing member; only a *new* invitation is refused once the Home is at or over its limit, mirroring Calendar's "preserve existing, block only new commitment" downgrade philosophy exactly.

Direct member-add flows beyond invitations were inspected and none exist — invitations are the only way a Home's member count grows beyond its creator, so this is complete enforcement, not partial.

### Personal and household routines

The Personal/Household routine split (`RoutineScope.personal` / `RoutineScope.household`, a real, DB-constrained distinction — `ck_routine_scope_owner`) already existed in the codebase before this task; this task only added commercial gating on top of it:

- `routines.personal.max_active` — `3` for Free, unlimited for Family. Enforced per-*person* (not per-Home) in `POST /homes/{id}/routines` and `PATCH .../routines/{id}` — counts a specific user's own enabled personal routines, under a per-`(home, user)` advisory lock. Disabling a routine (or deleting it) frees a slot immediately, since the count is always computed fresh from current `enabled=True` rows, never a persisted counter.
- `routines.household.enabled` — `False` for Free, `True` for Family. Enforced only on a genuine *transition into* household scope (creating a new household routine, or converting an existing personal routine to household) — exactly like Calendar's downgrade rule, an already-existing household routine on a since-downgraded Free Home remains fully editable for ordinary edits (title, timing, etc.); only a *new* commitment into the restricted state is blocked.

Both checks live in `routers/household_routines.py`, reusing `require_entitlement`/`require_within_limit` from `mykhaya.entitlements` — no bespoke enforcement logic was invented.

### Notes — corrected to Included on both plans

`notes.enabled` was previously (incorrectly) `False` for Free — the agreed model has Notes included on both plans, since it's a core-organiser feature, not a household-coordination one. Fixed to `True` for both. The underlying module remains unreleased (`mykhaya.module_registry` has no `notes` entry) — this is a correction to commercial *data*, not an early launch of the feature; nothing enforces or exposes it publicly until a real Notes module ships.

### Deferred enforcement (defined as data, not yet live)

Four keys exist in `PLAN_DEFINITIONS` as commercial data only, with **no** live enforcement, matching the precedent Phase 1 already established for `lists.enabled`/`chores.enabled`/`wishlists.enabled` (all still `hidden` modules, unchanged by this task):

- **`events.shared.enabled`** — "Shared family events" is not enforced. Investigation found ordinary multi-member events (`CalendarEventMember`) already work unrestricted on Free today; naively gating "any event with more than one participant" would be a breaking behaviour change to existing Free functionality with no clear product definition of what "shared" actually restricts. **Follow-up required**: a focused design task must define precisely what this differentiates (e.g. inviting members outside the Home? a dedicated "family event" type?) before any enforcement is added.
- **`members.external_invites.enabled`** — "Invite external members" has no backend capability behind it at all (`FeatureKey.external_sharing` is `hidden`, unimplemented scaffolding). Nothing to enforce yet.
- **`family_plans.enabled`** — "Family Plans" has no corresponding domain concept anywhere in the codebase. Declared as data only, per the existing "ready for whenever this exists" pattern — no placeholder module, route, or UI was created for it.
- **`support.priority.enabled`** — "Priority Support" is a support-policy property, not a software feature; MyKhaya has no support-ticket system to make this operationally real yet. Declared as data only.

None of these four appear in `GET /billing/plans` (public/household pricing comparison) — only in the Platform Control Centre's internal capability viewer, marked with a "Planned" badge, so an operator can see the intended model without it ever being advertised to a customer as something that works today.

### Platform Control Centre: plan capabilities vs current usage

The subscription detail page's entitlement viewer was split into two tables:

- **Plan capabilities** — every key from the agreed matrix above, in a fixed, curated order (never raw `Object.entries()` iteration over the API response), human-readable values ("Included"/"Not included"/"Unlimited"/"Up to 3"/"1 person"/"Whole household" — never `true`/`false`/`null`), with a "Planned" badge on the four deferred-enforcement keys.
- **Current usage** — household members, event categories (both with an "Over plan limit" badge when applicable, from the shared `member_usage`/`calendar_usage` helpers), and total personal routines in use across the Home (informational only — the limit itself is per person, so this aggregate is never compared against the limit directly, avoiding a misleading precision it can't actually deliver).

Both `member_usage` and `calendar_usage` reuse the same `CalendarUsageResponse` (`count`/`limit`/`over_limit`) shape rather than declaring a near-identical class per resource — the class name is a Phase 6 leftover, documented as intentionally generic rather than renamed, to avoid unnecessary churn across both backend and frontend call sites for a purely cosmetic improvement.

### Public and household pricing comparison

`GET /billing/plans` now returns four rows — People, Event categories, Personal routines, Household routines — all genuinely enforced and backed by reachable functionality today (routines are gated by the `notifications` feature flag, currently `beta`, not `hidden`, so they're real and working, unlike Lists/Chores/Wishlists). Still excludes every deferred-enforcement and unreleased-module key, unchanged from Phase 4/5's rule: an entitlement being technically defined is not sufficient reason to advertise it. No monetary figure was added anywhere — pricing continues to come exclusively from the Stripe-backed pricing service established in Phase 3.

### Explicitly out of scope for this cleanup

No Stripe billing/architecture change of any kind. No live billing enablement. No hard-coded prices. No enabling of Lists/Chores/Wishlists/Notes/Family Plans. No new commercial tier. No automatic deletion of over-limit data (a Home already exceeding the new Free member/routine limits keeps everything — only *new* growth is blocked, exactly like Calendar's existing downgrade model). No automatic member suspension or eviction. No enforcement of `events.shared.enabled` or `members.external_invites.enabled` (explicitly deferred, documented above as follow-up work).

## Free plan enforcement pass

A follow-up audit and correction pass, prompted by Free Homes still being able to reach Family functionality through surfaces the Commercial Plan Cleanup task above hadn't touched: the Home dashboard's "Invite family" action, the Family page's "Add member" button, the Routines form's freely-selectable "Household" scope, and — critically — two genuine backend bypasses of `home.max_members` that the previous pass's invite-creation-only check missed. No new entitlement keys were introduced; this closes gaps in *where* the existing `PLAN_DEFINITIONS` keys were actually being checked.

### Two real backend bypasses of `home.max_members`, now closed

1. **Invitation acceptance.** The previous pass checked `home.max_members` only at `POST /invitations` (invite *creation*). But a Home's effective plan can change between an invitation being sent and being accepted — a Family Home invites several people, then downgrades before they respond — and `POST /invitations/accept` added the resulting `Membership` unconditionally. Fixed by re-checking the limit in `accept()`, under the same `pg_advisory_xact_lock` pattern as `invite()`, but **only** when acceptance would actually grow membership (`existing is None or existing.removed_at is not None`) — a no-op re-accept of an already-active membership is exempt, since it doesn't increase the count. The invitation itself is never revoked by this check; it can still be accepted once the Home is Family again.
2. **Direct child-profile creation.** `routers.children.create_child` adds a full `Membership` row (relationship=`child`) directly — entirely separately from the invitation flow, with no invitation involved at all. It had no `home.max_members` check whatsoever. Fixed with the identical race-safe pattern (same lock key, `f"members:{group_id}"`, so it serialises against concurrent invitation acceptance for the same Home too).

Both fixes reuse `require_within_limit`/`commercial_restriction_error` unchanged — no new enforcement mechanism was invented.

### Frontend: gating that was missing, not wrong

The routine and household-routine entitlement *enforcement* from the Commercial Plan Cleanup task was already correct; what was missing was the frontend telling a Free user *before* they act rather than only after a rejected request:

- **Home dashboard** (`/home`): the "Invite family" quick action now only renders once `GET /groups/{id}/billing`'s new `member_usage` field confirms the Home can actually add another person — it fails closed (hidden) while that's still loading, never optimistically shown.
- **Family page** (`/people`): "Add member" is gated the same way; when the Home is at its member limit, a small "Invite household members — Available with MyKhaya Family" notice replaces it (never removes profile/member-viewing, per the "don't lock someone out of their own account" rule). The invite form itself is also gated as a second layer.
- **Routines form** (`/settings/routines`): the "Household" scope option is now `disabled` when the Home's plan doesn't include `routines.household.enabled` — a Free user can no longer select it and discover only on save that it's rejected. An existing household routine being edited on a since-downgraded Free Home keeps its option enabled specifically for that edit (so the transition-only downgrade-safety behaviour documented above still works from the UI, not just the API), with a Family upsell note shown alongside.
- **Settings → Plan & Billing**: gained a member-count "over plan limit" explanation, mirroring the existing calendar one, driven by the same new `member_usage` field.

A new `BillingStatusResponse.member_usage` (same `CalendarUsageResponse` shape as `calendar_usage`) and `household_routines_enabled: bool` field were added to `GET /groups/{id}/billing` specifically so these surfaces could gate correctly without each inventing its own entitlement lookup — the single household-facing read model Phase 4 already established stays the single source of truth.

### Seeded "categories" were never the commercial resource

Investigated why a test Home's UI showed several categories (Family/School/Work/Appointment/Birthday/Activity) despite Free being limited to one. These are `CalendarEventLabel` rows — free-form, unlimited event tags seeded once at Home creation (`routers.groups.DEFAULT_LABELS`) — not `HomeCalendar` rows, and were never counted against `calendar.max_categories`; a Free Home has exactly one persisted `HomeCalendar` ("Home Calendar") at creation, as designed. The actual bug was cosmetic: the Calendar page's label filter dropdown was accessibility-labelled "Calendar or category", which reads as if it were the entitlement-limited resource. Relabelled to "Filter by label" so the two concepts are never conflated again — no change to the underlying `CalendarEventLabel` model, seeding, or limits.

### Shared family events — still deferred, not silently broadened

Re-confirmed the Commercial Plan Cleanup task's original conclusion: `events.shared.enabled` remains commercial data only, unenforced. In practice, `home.max_members = 1` already prevents a *newly created* Free Home from having more than one person to share an event with in the first place, so the live bypass surface is narrower than it looks; a Family Home that downgrades while retaining multiple existing members can still assign them to shared events, which is intentional (non-destructive downgrade — "preserve existing, block only new growth" applies here exactly as it does to calendars and routines). A real product definition of what "shared" restricts is still required before any enforcement is added.

### Test account reproduction — before / after

The exact scenario reported (a Free Home with one member) is now covered directly by `apps/api/tests/test_free_plan_enforcement.py`:

| | Before this pass | After this pass |
|---|---|---|
| Invite a second household member | Blocked at invite *creation* only — an already-sent invite could still be accepted after a downgrade | Blocked at both creation and acceptance |
| Add a child | Not blocked at all — no entitlement check existed | Blocked once at the member limit |
| Select "Household" for a routine | Selectable in the UI, rejected only after submitting | Disabled in the UI before submission; API enforcement unchanged (was already correct) |
| Multiple event categories | Never actually possible on a genuinely Free Home (label/category confusion was cosmetic only) | Unchanged — confirmed, not a real gap |
| Calendar, Events, Notes, up to 3 Personal routines | Fully available | Unchanged — fully available |

### Explicitly out of scope for this pass

Unchanged from the Commercial Plan Cleanup task: no Stripe/billing changes, no live billing, no hard-coded prices, no enabling of Lists/Chores/Wishlists/Family Plans, no new commercial tier, no automatic deletion or suspension of over-limit data. `events.shared.enabled` and `members.external_invites.enabled` were deferred as of this section — see "Free plan enforcement pass, part 2" below, where both gained real enforcement.

## Free plan enforcement pass, part 2: shared events and the remaining declared gaps

A follow-up to the section above, closing three things a review found still relied on indirect signals rather than their own entitlement: shared events were only ever prevented by `home.max_members` (a Free Home simply had no one to share with, rather than the capability itself being checked), and `members.external_invites.enabled`/`family_plans.enabled`/`support.priority.enabled` remained plan data with no enforcement architecture behind them at all.

### `events.shared.enabled` — enforced directly, not derived from the member limit

Previously, a Free Home couldn't create a multi-participant event only because it's capped at one member — there was nothing to actually check `events.shared.enabled` against. This meant a downgraded Family Home that *kept* several members (the member limit only blocks new growth, never evicts anyone) could still freely assign new participants to events, since nothing was checking the real entitlement.

`routers.calendar.create_event` now requires `events.shared.enabled` whenever the final participant set exceeds one person. `update_event` applies the same "genuinely new participant" test already established for household routines and Extended Family conversion: it computes `genuinely_new_participants = requested_members - previous_member_ids` and only requires the entitlement when that set is non-empty **and** the result is still a multi-person event. This means:

- Creating a new shared event on Free: blocked.
- Converting a personal (single-participant) event to shared on Free: blocked (a special case of the above — `previous_member_ids` is just the creator).
- Adding a participant to an already-shared historical event on Free: blocked — growing an existing shared event is still a *new* commitment.
- Removing a participant from a shared event, or editing any other field while keeping the exact same participant set: always allowed, at any plan — this is what makes a historical shared event survive a downgrade with its participant set intact, exactly as the "preserve historical data, block new paid-feature usage" rule requires.

There is no duplicate/copy-event endpoint in the codebase to separately audit — `create_event`/`update_event` are the only two places `CalendarEventMember` rows are ever written.

Covered by `apps/api/tests/test_shared_event_entitlements.py` (8 tests): Family can create a shared event; a downgraded Home cannot create a new one; Free can still create an ordinary personal event; a downgraded Home's historical shared event survives with its participants intact; a downgraded Home cannot convert a personal event to shared, cannot add a participant to a historical shared event, but *can* remove one; and editing unrelated fields on a historical shared event never touches its participant set.

**Frontend**: the Calendar event form's "Household members" checkboxes now disable any box that isn't already checked when `shared_events_enabled` (a new `GET /groups/{id}/billing` field) is false — an already-assigned participant's checkbox always stays interactive so removing them (or simply re-saving the event) never breaks, but no new name can be ticked. A disabled-but-unchecked checkbox is correctly omitted from the submitted form data (disabled checked boxes are not, which is why only never-checked boxes are ever disabled).

### `members.external_invites.enabled` — a real, reachable capability, now enforced

Investigation found Extended Family/Friend is not a stub: it's a fully working relationship type (`PermissionProfile.explicit_sharing` — zero default capabilities, selectively granted `shared_resources` like `"calendar"`), reachable both at invitation creation (`POST /invitations`) and by changing an existing member's relationship (`PATCH /groups/{id}/members/{user_id}`). Both now require `members.external_invites.enabled`, checked independently of `home.max_members` (today Free's member cap already blocks any invite regardless, but this entitlement is what actually governs *this relationship type specifically*, and must keep doing so if a future plan ever allows more than one Free member). The relationship-change endpoint uses the same "genuinely new transition" pattern as everywhere else: converting an ordinary member *into* Extended Family/Friend is blocked on Free, but a member who already holds that relationship keeps working normally (including editing their `shared_resources`) — transition-safe, non-destructive.

Covered by `apps/api/tests/test_external_invite_entitlements.py` (5 tests). Frontend: the invite form and the per-member "Change relationship" selector both disable the Extended Family/Friend options (with a "(Family)" suffix and an upsell note) unless already reachable — mirroring the same transition-safe rule (an existing external member's own current option stays selectable).

### `family_plans.enabled` and `support.priority.enabled` — contract only, no feature surface

Re-confirmed by direct search: no router, service, background task, serializer, or frontend component anywhere in the codebase touches either capability, beyond the entitlement definition itself and its display in the Platform Control Centre. There is nothing to enforce and, per instruction, nothing was invented to enforce against. Both remain exactly as `test_entitlements.py`'s `test_free_resolves_the_full_agreed_capability_matrix` / `test_family_resolves_the_full_agreed_capability_matrix` / `test_every_family_provider_variant_resolves_identical_capabilities` already pin them (Free `False`, Family `True`, identical across every Family provider/status) — this is the "central capability contract" a future implementation must build against.

**This is a different, stronger statement than "deferred enforcement":** deferred enforcement (as `events.shared.enabled`/`members.external_invites.enabled` briefly were) means a reachable feature exists but isn't yet gated. Contract-only means there is no feature at all yet — only a pinned entitlement key and a test that will fail the moment anyone builds something for it without wiring it through `mykhaya.entitlements` first. The Platform Control Centre's capability viewer now labels these two "Contract only" (distinct from "Planned", which still means a real, hidden module) so an operator never mistakes either state for "usable today" or confuses the two different kinds of not-yet-real.

### Downgrade semantics — re-audited

Every Family-only object already representable in the data model was re-checked against "preserve historical paid data, block new paid-feature usage while Free": household routines (existing ones keep working, only a new commitment into household scope is blocked — Commercial Plan Cleanup task), shared events (this section), event categories/calendars (Phase 6 — excess categories go read-only, never deleted), household members and Extended Family/Friend relationships (this section and the prior pass — never evicted, only new growth blocked). No code path in any of these deletes or silently mutates existing data as a side effect of a plan change.

### Test result (this delta)

`sh infrastructure/scripts/run-tests.sh`: **538 passed, 2 failed**. The 2 failures (`test_migration_integrity.py::test_alembic_revision_ids_fit_version_column_and_form_one_chain`, `test_worker.py::test_database_rejects_duplicate_scheduler_occurrence`) are unrelated to commercial entitlements — reproduced identically (same 2 failures) on the pre-existing baseline commit (`382c278`, before any of this pass's work) via an isolated `git worktree`, and their failure content (an Alembic-migrations-directory glob returning empty; a `MissingGreenlet` error from re-reading an ORM attribute after a rollback in a scheduler-occurrence test) has no connection to entitlements, plans, members, events, or routines.

## Event categories are CalendarEventLabel, not HomeCalendar

A production-blocking correction: a review found that a Free Home could visit Settings -> Home settings' "Calendars & categories" page and see (and freely activate, rename, recolour) all 7 seeded default categories — Family, School, Work, Appointment, Birthday, Activity, Other — with no plan restriction whatsoever, directly contradicting "Free = 1 event category". The Commercial Plan Cleanup and Free Plan Enforcement passes above had correctly enforced `calendar.max_categories` against `HomeCalendar` creation (the `/calendar/calendars` page, itself relabelled "Event categories" during that work) — but `HomeCalendar` is not the resource this settings page manages, or the resource an ordinary user experiences as "category". This page manages `CalendarEventLabel` rows, and its own copy says so plainly: *"Every event belongs to one of these — its colour, not who created it, is what shows on Calendar."* That is the actual, user-facing event-category feature. The earlier passes enforced the right entitlement key against the wrong resource.

### The corrected model

- **Calendar** — the container itself (`HomeCalendar`). Always included on both plans. A Free Home structurally has exactly one (Phase 6, unchanged).
- **Event category** — `CalendarEventLabel`. The thing every event belongs to; its colour is what Calendar renders. **This is what `calendar.max_categories` now also governs** — Free: 1 active, Family: unlimited. Managed at Settings -> Home settings, and selected per-event via the "Calendar or category" field on the Calendar page.
- **Label/tag** — there is no third, separate "tag" concept; `CalendarEventLabel` *is* both the category and what was previously called a "label" internally. The class name stays `CalendarEventLabel` (cosmetic rename avoided, per the established pattern of not renaming a model merely for terminology alignment) but its commercial treatment is now correct.

Both `HomeCalendar` and `CalendarEventLabel` share the single `calendar.max_categories` entitlement key rather than each having their own — reusing one entitlement across two independently-tracked resources, not a second plan-checking system. In practice a Free Home is capped at 1 of each, which is what "1 event category" actually means end to end on every surface a customer can reach.

### Seeding fixed at the source

`routers.groups.create_group` (Home creation) and `routers.calendar._ensure_home_calendar` (the lazy fallback) both previously seeded all 7 `DEFAULT_LABELS`/`SYSTEM_LABELS` with `is_active=True`. Now only the first (`"Family"`) starts active; the other 6 are seeded `is_active=False`. Every new Home is Free at creation time (per the standing signup rule), so this is correct unconditionally — a Home that upgrades to Family can activate the pre-seeded rest (or create new ones) without needing to re-type anything.

### Backend enforcement

`routers.calendar.create_label` and `update_label` (the only two label-mutating endpoints — there is no delete, no duplicate/copy) now enforce `calendar.max_categories`, race-safe under the same `pg_advisory_xact_lock` pattern as calendar/member/routine creation:

- **Create**: a new label is always active, so creating one when already at the limit is blocked outright (`plan_limit_reached`).
- **Activate**: transition-safe — only `is_active: false -> true` is checked (excluding the label's own row from the count). Deactivating, renaming, or recolouring a label is never blocked, at any plan — this is what lets a user "rename/customise their one usable entry" freely and lets a Family Home reorganise without hitting a race against its own edits.

`create_event`/`update_event` gained the same `_require_label_selectable` check `_require_calendar_writable` already provided for `HomeCalendar`: a `label_id` must resolve to a label the Home can currently use (`classify_ordered_resources` over the active set, same deterministic "lowest sort_order/oldest wins" ordering as calendars). For `update_event`, this is transition-safe exactly like the shared-events check — only a genuine label *change* is validated; resaving an event with the label it already has is always allowed, which is what lets a historical event assigned to a since-downgraded, over-limit label keep rendering and being edited (title, time, other fields) indefinitely.

### Downgrade behaviour

Deactivating labels is never automatic. A Family Home with 3 active labels that downgrades keeps all 3 rows `is_active=True` in the database — nothing is deleted or flipped. What changes is which one is usable for *new* activity: `GET /event-labels?include_inactive=true`'s `commercial_access` (computed fresh every read, exactly like `HomeCalendar.commercial_access`) marks the lowest-`sort_order` active label `"normal"` and the rest `"read_only_due_to_plan"`. A locked label can still be viewed, still renders on every historical event that already carries it, and can still have events resaved against it unchanged — it just can't be assigned to a *new* event, reactivated, or have a brand-new label created alongside it, until the Home is Family again (at which point every preserved label becomes usable immediately, no migration or manual re-activation needed) or enough labels are manually deactivated to fall back under the limit.

### Frontend

- **Settings -> Home settings "Calendars & categories"** (`app/settings/home/page.tsx`): now fetches `include_inactive=true` so every label — not just the currently-active one — is visible. A `commercial_access: "read_only_due_to_plan"` row renders muted, with a lock icon and "Family" indicator, no working "Active" checkbox, no rename/recolour controls (Option A from the review). The create form is replaced entirely by a locked "Add another category 🔒 — Unlimited categories are included with MyKhaya Family" card (`FamilyUpsell`, Option B) once the Home is at its limit — driven by a new `category_usage` field on `GET /groups/{id}/billing`, computed by the new `mykhaya.entitlements.category_usage` (parallel to the existing `calendar_usage`/`member_usage`).
- **Calendar page's event-category selector** (`app/calendar/page.tsx`): the same transition-safe locking as the routine-scope and household-member selectors — a locked category shows `disabled` with a "(Family)" suffix, except when it's the event's own current category (so editing an existing event never breaks).
