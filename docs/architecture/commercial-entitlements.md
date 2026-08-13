# Commercial Entitlements

Phase 1 of MyKhaya's commercial architecture: plans, Home-level subscriptions and an entitlement-resolution service. Phase 2 (below, "Platform Control Centre subscription management") builds the read-only-plus-complimentary-only operational UI on top of it. Stripe integration (Phase 3) is the only remaining phase that talks to a real payment provider — nothing in Phase 1 or Phase 2 does, and neither builds a payment form.

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
