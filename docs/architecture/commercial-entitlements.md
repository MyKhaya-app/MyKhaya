# Commercial Entitlements

Phase 1 of MyKhaya's commercial architecture: plans, Home-level subscriptions and an entitlement-resolution service. This is the foundation Stripe integration (Phase 3) and the Platform Control Centre billing UI (Phase 2) build on — neither exists yet. Nothing here talks to Stripe, and nothing here is a payment form.

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

## Explicitly out of scope for this phase

No Stripe SDK, Checkout, webhooks, or customer portal. No payment forms. No pricing pages. No payment step in signup. No Apple/Google in-app billing. No Plan & Billing UI for households. No subscription-management UI in the Platform Control Centre beyond the grant/revoke complimentary endpoints and the read-only subscription block on the existing Home detail page — those exist so Phase 2's UI has something to call, not as the UI itself.
