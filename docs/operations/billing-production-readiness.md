# Billing Production Readiness (Phase 7)

Operator runbooks for taking MyKhaya's Stripe billing from "built and tested with
mocks" (Phases 1–6) to "safe to actually enable." This document does not itself
enable anything — every procedure here either verifies configuration or requires a
deliberate, separate operator action. See
`docs/architecture/commercial-entitlements.md` (Phase 7 section) for the underlying
design, and `docs/security/platform-administration-security.md` (Phase 7 section) for
the security review.

## The two gates

```
MYKHAYA_STRIPE_BILLING_CONFIGURED=true          — Stripe is set up (test or live)
MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=true — new paid signups are actually allowed
```

Both are environment variables (restart required), both default `false` everywhere
including production. Acquisition can never be `true` while configuration is
`false` (enforced at startup). Existing Stripe-backed Homes, webhooks, renewals,
cancellations, the Customer Portal, and reconciliation are **never** gated by
acquisition — only a brand-new Checkout Session is. See "Billing disable / rollback"
below for the operational implication.

## Readiness command

```sh
infrastructure/scripts/billing-readiness.sh
infrastructure/scripts/billing-readiness.sh --check-stripe   # also calls the live Stripe API (test mode only)
```

Runs `mykhaya.billing_readiness` inside the real `api` service (this deployment's
actual configuration, not the isolated test stack). Prints `PASS`/`WARN`/`BLOCKER`
per check, never a secret value. `--check-stripe` additionally verifies the
configured Price IDs resolve against the real Stripe API — it refuses to run against
a live-mode (`sk_live_`) key, so it can never accidentally touch live Stripe data.

This command tells you whether **configuration** is internally consistent. It does
**not** tell you whether the real Stripe sandbox lifecycle has been verified, or
whether the business/legal decisions below have been made — see the go-live
checklist.

## Real Stripe sandbox verification

**This is mandatory before considering live billing ready**, and mocked-Stripe test
coverage (the default for `sh infrastructure/scripts/run-tests.sh`) does not
substitute for it. If real Stripe test-mode credentials are not available to
whoever is running this, this step is an explicit launch blocker — do not report it
as done.

### One-time sandbox setup

1. Create/use a Stripe account, switch to **test mode**.
2. Create a `MyKhaya Family` Product with a monthly and an annual recurring Price
   (any currency/amount — this is test mode).
3. Set `MYKHAYA_STRIPE_SECRET_KEY` (test key), `MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID`,
   `MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID`, `MYKHAYA_STRIPE_BILLING_CONFIGURED=true`.
   Leave `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=false` for now — Checkout is
   still exercised directly against Stripe's test-mode hosted page even with
   acquisition off is not true; acquisition must be `true` to actually start
   Checkout. Set it `true` for the duration of this verification, then back to
   `false` afterwards unless you're deliberately proceeding to launch.
4. Forward webhooks locally with the Stripe CLI:
   `stripe listen --forward-to <host>/api/v1/billing/stripe/webhook` — use the
   ephemeral `whsec_...` it prints as `MYKHAYA_STRIPE_WEBHOOK_SECRET`.
5. Run `infrastructure/scripts/billing-readiness.sh --check-stripe` and confirm no
   `BLOCKER` lines.

### Lifecycle to walk through, and what to record

For each step below, record: what was done, which real Stripe object ID/event type
was observed (never a secret), and the outcome. Do this for **both** monthly and
annual — do not skip annual because monthly passed.

1. Create a Free Home; confirm `effective_plan` is Free.
2. Load `GET /billing/pricing`; confirm it shows the real configured test Price.
3. Start Checkout (monthly), confirm the request to
   `POST /groups/{id}/billing/checkout-session` sends only `{"interval": "month"}`.
4. Complete Stripe's hosted test Checkout with `4242 4242 4242 4242` (any future
   expiry/CVC).
5. Confirm the browser return (`?checkout=success`) shows the "confirming" state,
   **not** immediate Family — then confirm the Stripe CLI shows
   `checkout.session.completed` followed by `customer.subscription.created`
   delivered and returning `200`.
6. Confirm the Home is now Stripe-backed Family (`effective_plan` = Family,
   Settings → Plan & Billing shows the real Stripe price, Platform Control Centre's
   subscription detail shows the real Customer/Subscription IDs and
   `recent_webhook_events`).
7. Confirm a second calendar can now be created (Family entitlement live).
8. Repeat 3–7 for annual — different Price ID, different `billing_interval` stored,
   same commercial plan (Family), same entitlements.
9. **Abandonment**: start Checkout, close the tab before paying. Confirm the Home
   stays Free, the account stays valid, retry works, and no duplicate Stripe
   Customer/Subscription was created.
10. **Duplicate protection**: attempt Checkout twice in quick succession (two tabs,
    or the monthly/annual buttons pressed near-simultaneously). Confirm only one
    live subscription results — the existing advisory lock plus
    `DuplicateSubscriptionError` should prevent a second.
11. **Renewal**: use a
    [Stripe test clock](https://docs.stripe.com/billing/testing/test-clocks) attached
    to the test Customer, advance it past the renewal date, confirm
    `invoice.payment_succeeded` arrives, `current_period_end` advances, the Home
    stays Family, no duplicate commercial-history row is written, and the grandfathered
    Price ID is unaffected if you've since changed the public signup Price (see
    "Grandfathered pricing verification" below).
12. **Failed payment**: on the test clock, advance to a renewal using Stripe's
    documented `4000 0000 0000 0341` (attaches, then fails on charge) or the test
    clock's built-in failure simulation. Confirm `invoice.payment_failed` arrives,
    the Home becomes `past_due`, Family access is **retained**, Settings → Plan &
    Billing shows "Payment needs attention," the Customer Portal remains reachable,
    and Platform Control Centre reflects `past_due`.
13. **Cancel at period end**: via the Customer Portal, schedule cancellation.
    Confirm MyKhaya shows "Cancels on DATE," effective plan is still Family, the
    calendar entitlement is still full. Then undo it in the Portal if supported,
    and confirm MyKhaya returns to normal active presentation.
14. **Final cancellation**: let the test clock advance past the cancelled period
    end, or cancel immediately via the Dashboard. Confirm `customer.subscription.deleted`
    arrives, effective plan becomes Free, **no calendar or event is deleted**, the
    primary calendar stays usable, any excess calendars become read-only per Phase
    6, and Plan & Billing shows the ended state.
15. **Re-upgrade**: start a fresh Checkout from the now-Free Home, complete payment,
    confirm the webhook arrives and Family (including any previously-restricted
    calendars) is fully restored with no manual/database intervention.
16. **Customer Portal**: confirm a billing manager can open it, a non-manager
    household member cannot start the flow, it targets the correct Customer,
    payment-method update works, and the return lands back on MyKhaya cleanly.

### Grandfathered pricing verification

1. Create `Family Monthly v1`, subscribe a test Home to it (steps above).
2. In the Stripe Dashboard, create `Family Monthly v2`, update
   `MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID` to v2, redeploy config only (no code
   change).
3. Confirm `GET /billing/pricing` now shows v2; confirm a **new** Checkout uses v2.
4. Confirm the **existing** v1 subscriber's Plan & Billing page still shows v1's
   actual price, and `HomeSubscription.external_price_id` is still v1.
5. Trigger reconciliation for that Home (Platform Control Centre) — confirm it does
   **not** "upgrade" the Home to v2; reconciliation reflects Stripe's own state,
   which is still v1 until the customer's subscription itself changes.

### What was actually verified in this engagement

No Stripe test-mode credentials were available in this environment (confirmed:
`.env` has no Stripe values, `.env.example` ships them blank, no `STRIPE_*` value in
the shell). **None of the real-sandbox steps above were performed.** Everything in
this document was validated against a mocked Stripe SDK (`monkeypatch` on
`stripe.Price`/`stripe.Customer`/`stripe.checkout.Session`/`stripe.billing_portal.Session`/
`stripe.Webhook.construct_event`/`stripe.Subscription`) via
`sh infrastructure/scripts/run-tests.sh`. Treat the numbered checklist above as the
**exact procedure to run** the first time real credentials are available — not as
already-completed evidence.

## Price rotation (a future price increase)

Prices are normally rotated through the Platform Control Centre's Payments page
(**Settings → Payments → Stripe**) rather than by editing environment configuration —
the steps below apply either way; only step 3 differs by path.

1. Create the new Stripe Price in the Dashboard (test or live). Never edit an
   existing Price's amount — Stripe Prices are immutable; create a new one.
2. Verify it (readiness command with `--check-stripe`, or a manual test Checkout).
3. Update the Monthly/Annual Price ID for the active mode:
   - **Control Centre path (primary)**: Payments page → the active mode's section →
     update the Price ID field → Save changes. Takes effect immediately, no restart,
     and is written to the platform audit log (`stripe.settings_changed`).
   - **Environment fallback path**: update `MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID` /
     `..._ANNUAL_PRICE_ID` in deployment configuration and restart/redeploy — only
     takes effect if no Platform-Admin-managed Stripe configuration is enabled (see
     `docs/architecture/platform-control-centre.md#stripe-configuration-precedence`).
   Never edit a price figure in source — there isn't one, either way.
4. Confirm `GET /billing/pricing` reflects the new Price (cache TTL is 5 minutes —
   a restart, or another settings save, clears it immediately if needed sooner).
5. Confirm a **new** Checkout uses the new Price.
6. Confirm existing subscribers remain on their old Price (`external_price_id`
   unchanged) — see "Grandfathered pricing verification" above.
7. Archive the old Price in the Stripe Dashboard for *new* sales once confident
   (this doesn't affect existing subscriptions) — optional, operator judgement.

## Stripe secret API key rotation

Secret keys are normally rotated through the Payments page's **Replace** action
(**Settings → Payments → Stripe → Secret key → Replace**), which requires recent
re-authentication and a reason, and is written to the platform audit log as
`stripe.test_secret_key_replaced` / `stripe.live_secret_key_replaced` — the action
only, never the key value. The environment variable remains a supported
bootstrap/fallback path for deployments that haven't enabled Control Centre-managed
Stripe configuration.

1. In the Stripe Dashboard, create a new restricted (see "Least-privilege
   credentials" below) or standard secret key — do **not** reuse or edit the
   existing one; Stripe keys aren't editable in place.
2. **Control Centre path (primary)**: paste the new key into the active mode's
   Secret key field and Save changes. Takes effect immediately for the next
   request — no restart, no window where two keys are simultaneously in use.
   **Environment fallback path**: deploying the new key as `MYKHAYA_STRIPE_SECRET_KEY`
   alongside the still-valid old one is not supported (only one environment key is
   read) — plan for a short window: set the new key, restart, verify
   (`billing-readiness.sh --check-stripe`), then revoke the old key.
3. Verify: pricing loads, a test Checkout can be created, Portal session creation
   works, and (Control Centre path) the **Test Stripe connection** action reports
   "Connected".
4. Revoke the old key in the Dashboard only after the new key is confirmed working.
5. **Rollback**: if the new key doesn't work, restore the previous value (via the
   Payments page's Replace action, or by reverting the environment variable and
   redeploying) — do not revoke the old key in the Stripe Dashboard until the new
   one is proven.
6. Record who rotated it and why. On the Control Centre path this is already
   captured by the platform audit log (administrator identity, timestamp, action);
   on the environment fallback path, MyKhaya has no application-level audit trail
   for environment-variable changes, since Stripe secrets there never touch the
   database or the platform-audit log — record it via your usual
   change-management process instead.

## Webhook signing secret rotation

Stripe supports [multiple simultaneous webhook endpoints](https://docs.stripe.com/webhooks#register-endpoint) —
use this for zero-downtime rotation rather than a single cutover that risks a gap:

1. Register a **second** webhook endpoint in the Stripe Dashboard pointing at the
   same MyKhaya URL, and note its own signing secret.
2. MyKhaya currently supports exactly **one** configured webhook signing secret per
   mode (`platform_stripe_settings.encrypted_test_webhook_secret` /
   `encrypted_live_webhook_secret` on the Control Centre path, or
   `MYKHAYA_STRIPE_WEBHOOK_SECRET` on the environment fallback path) — there is no
   multi-secret support built. This means true zero-downtime *application-level*
   rotation isn't available today; treat this as a documented gap. The safe sequence
   with a single-secret application is: register the new endpoint, confirm it
   delivers successfully (Stripe will send to both endpoints simultaneously during
   the overlap), update the webhook secret to the new endpoint's secret (Payments
   page's Replace action, primary path — or `MYKHAYA_STRIPE_WEBHOOK_SECRET` plus a
   restart, fallback path), confirm new deliveries verify successfully, then delete
   the *old* endpoint in the Dashboard. The overlap window (both endpoints
   registered, old secret still configured) is short and Stripe's own retry
   behaviour means a missed event in that window is redelivered automatically.
3. If sub-second webhook availability during rotation becomes a real requirement,
   the fix is adding support for a second, overlapping webhook secret setting per
   mode — not built; documented here as the identified follow-up rather than built
   speculatively.

## Webhook failure recovery

- **First line of defence: Stripe's own automatic retries** — a non-2xx response
  (which is what MyKhaya returns on any processing failure) is retried by Stripe on
  its own schedule; most transient failures self-resolve without operator action.
- **Observability**: `GET /platform/subscriptions/webhook-health` (Platform Control
  Centre → Subscriptions) shows recent failures and the deployment-wide health
  state; a Home's own subscription detail page shows its `recent_webhook_events`.
- **If failures persist for a specific Home**: use the existing per-Home
  reconciliation action (below) — it re-fetches live Stripe state directly, which
  self-heals most drift without needing the original failed webhook to succeed.
- **No generic "replay this event" button exists** — deliberately: an operator
  replaying an arbitrary captured payload would bypass Stripe's own signature
  trust. If a specific event genuinely needs manual reprocessing beyond what
  reconciliation covers, use the Stripe Dashboard's own "resend event" action
  (Developers → Webhooks → the specific endpoint → the specific event) — this goes
  through MyKhaya's normal signature-verified path exactly like the original
  delivery.

## Reconciliation

**Single Home**: Platform Control Centre → Subscriptions → the Home → "Reconcile
with Stripe" — re-fetches the Home's live Stripe Subscription and re-applies it
through the same normalized state machine webhooks use. Requires `OPERATORS` role +
recent authentication, is audited (`home.subscription_reconciled`), and is rejected
with `409` if the retrieved Subscription's own metadata doesn't match the Home (see
"Reconciliation authority" in the security doc) — this should never fire in normal
operation; if it does, treat it as a data-integrity incident, not a routine retry.

**Bulk (outage recovery)**: not built as a UI/endpoint at current scale — see
"Bulk reconciliation" in the architecture doc for why. If needed after a webhook
outage or deployment failure, the safe scripted approach is:

```sh
# Inside the api container, or via a one-off script using the same session/DB access
# the app already uses — reconciles every Stripe-backed Home sequentially, respecting
# Stripe's own rate limits by not parallelising.
docker compose run --rm --no-deps api python -c "
import asyncio
from sqlalchemy import select
from mykhaya.billing.config import resolve_stripe_config
from mykhaya.billing.reconciliation import reconcile_home_subscription
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import HomeSubscription, SubscriptionProvider

async def main():
    settings = get_settings()
    config = resolve_stripe_config(settings)
    async with SessionFactory() as db:
        rows = (await db.scalars(
            select(HomeSubscription).where(HomeSubscription.provider == SubscriptionProvider.stripe)
        )).all()
        for row in rows:
            try:
                await reconcile_home_subscription(db, config, row.group_id, actor_administrator_id=None)
                await db.commit()
                print(f'reconciled {row.group_id}')
            except Exception as exc:
                await db.rollback()
                print(f'FAILED {row.group_id}: {exc}')

asyncio.run(main())
"
```

This reuses the exact same `reconcile_home_subscription` function the single-Home
UI action calls (no separate mutation path), runs sequentially (no API storm), and
prints per-Home progress. `actor_administrator_id=None` means these transitions
show as system-driven in commercial history, not attributed to a specific operator
— acceptable for outage recovery; if per-operator attribution is wanted, pass a
real administrator ID.

## Stripe outage behaviour (reference)

| Situation | Behaviour |
|---|---|
| Existing paid Home, ordinary use | Unaffected — entitlement resolution never calls Stripe |
| New Checkout attempt | `503`, Home stays Free, no partial state |
| Public pricing | `503` with "temporarily unavailable, Free still available"; never a stale hard-coded figure |
| Customer Portal | `503`, clear non-leaking message |
| Reconciliation | Reports provider-unavailable; never mutates local state on a failed Stripe call |

Never fails open into Family. Never fails closed by stripping existing paid access
merely because Stripe can't currently be reached.

## Database backup/restore implications

Commercial records (`home_subscriptions`, `home_subscription_events`,
`stripe_webhook_events`, `stripe_webhook_failures`) are ordinary tables in the main
MyKhaya database and are included in the standard `infrastructure/scripts/backup.sh`
backup — no special handling needed to capture them.

**A restored database is stale relative to Stripe** if real payments continued
processing after the backup was taken. Always follow a restore with:

```
Restore MyKhaya database (infrastructure/scripts/restore.sh)
        ↓
Reconcile every Stripe-backed Home (bulk procedure above)
        ↓
Verify webhook endpoint health (billing-readiness.sh, then watch
GET /platform/subscriptions/webhook-health for a few minutes of live traffic)
```

Do not assume a restore alone leaves commercial state correct — it leaves MyKhaya's
copy of Stripe's state as of the backup time, which reconciliation then corrects
against Stripe's actual current state.

## Deployment rollback safety

Migration `0023_billing_readiness` only **adds** a new table
(`stripe_webhook_failures`) and has a clean `downgrade()`. It does not modify or
remove any existing column, so rolling back to a pre-Phase-7 release is safe:
`stripe_webhook_events`/`home_subscriptions` and their data are untouched by a
downgrade. A rolled-back release simply stops writing to (and reading from)
`stripe_webhook_failures`; existing webhook dedup/processing is unaffected since
that logic lives entirely in `stripe_webhook_events`, unchanged by this phase.

## Billing disable / rollback (stop new purchases immediately)

To stop new paid acquisition without disrupting existing subscribers:

1. Set `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=false`, redeploy/restart.
2. **Leave the webhook endpoint enabled** — existing subscribers' renewals,
   cancellations, and payment-failure events must keep processing (verified by
   `test_webhook_processing_unaffected_by_acquisition_disabled`).
3. **Leave the Customer Portal enabled** — existing customers can still manage/
   cancel their own subscription.
4. Local paid entitlements are unaffected — nothing about this flag touches
   `HomeSubscription` rows.
5. Investigate whatever prompted the disable.
6. Reconcile any Homes affected by the incident (see Reconciliation above).
7. Re-enable (`MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=true`) only once resolved.

## Least-privilege Stripe credentials (recommended)

MyKhaya's Stripe usage is narrow enough for a
[restricted key](https://docs.stripe.com/keys#limit-access) rather than the
unrestricted secret key used during development:

| Resource | Access needed |
|---|---|
| Customers | Write |
| Checkout Sessions | Write |
| Billing Portal Sessions | Write |
| Subscriptions | Read |
| Prices | Read |
| Webhook Endpoints | None (the signing secret is configured directly, not fetched via API) |

Everything else can be set to "None." This is a recommendation for the live
credential — MyKhaya makes no assumption about key scope in code, and an
unrestricted key continues to work identically.

## Production webhook endpoint

- **URL**: `https://<your-domain>/api/v1/billing/stripe/webhook` — HTTPS required in
  production (enforced generally by `MYKHAYA_COOKIE_SECURE`/production settings,
  though this specific route needs no cookie).
- **Events**: exactly the six MyKhaya handles —
  `checkout.session.completed`, `customer.subscription.created`,
  `customer.subscription.updated`, `customer.subscription.deleted`,
  `invoice.payment_succeeded`, `invoice.payment_failed`. Do not subscribe to the
  entire account event stream — anything else is acknowledged and ignored anyway,
  but a narrower subscription list is easier to audit and reduces noise.
- **Signing secret**: the endpoint's own secret (`whsec_...` from the Dashboard, not
  the Stripe CLI's ephemeral one used for local development) as
  `MYKHAYA_STRIPE_WEBHOOK_SECRET`.
- **No session/authentication required** — trust is Stripe's cryptographic
  signature alone (`mykhaya.billing.webhooks.verify_and_parse_event`), never a
  cookie or CSRF token; this route deliberately sits outside the normal
  cookie-authenticated request path.
- **Raw body integrity**: the handler reads `await request.body()` directly and
  passes those exact bytes to signature verification — any reverse proxy/load
  balancer in front of the API must not rewrite, re-encode, or gzip-transcode the
  request body before it reaches the app, or signature verification will fail for
  every delivery. Verify this explicitly against your actual production proxy
  configuration before registering the live endpoint.
- **Return URLs** (Checkout success/cancel, Portal return) are always built from
  `MYKHAYA_PUBLIC_WEB_URL`, never from request `Host`/forwarded headers or a
  request parameter — confirm this value is the real production URL before
  registering.

## Refund / support workflow

MyKhaya has **no refund button** — deliberately, per Phase 7's scope. Stripe remains
the payment processor and the source of truth for money movement. A support
operator handling "I want a refund" or a billing dispute:

1. Find the Home in Platform Control Centre → Subscriptions.
2. Read off the Stripe Customer reference and Subscription reference from the
   subscription detail page (or the "Open in Stripe" dashboard links, when in test
   mode these point at the test dashboard).
3. In the Stripe Dashboard, locate the Customer → the relevant invoice/payment →
   issue the refund there. Stripe's own refund flow handles the payment-provider
   side; MyKhaya's commercial state (plan/entitlement) is unaffected by a refund
   unless the associated subscription is also cancelled (which then flows through
   the normal webhook path exactly like any other cancellation).
4. If the refund should also end the subscription, cancel it in Stripe (via
   Dashboard or Portal) — the existing webhook path handles the resulting Free
   downgrade safely, preserving all data per Phase 6.

## Chargeback / dispute readiness

MyKhaya does **not** subscribe to Stripe's dispute-related webhooks
(`charge.dispute.*`) — deliberately, to avoid building automation against an event
category with no defined MyKhaya-side action yet. If Stripe reports a dispute:

- The Stripe Dashboard is the authoritative place to view and respond to it.
- **Do not automatically terminate or delete the Home** — no such automation exists,
  and none should be added without an explicit product/business policy decision.
- Commercial and audit history is preserved regardless; a dispute has no automatic
  effect on `HomeSubscription` unless/until the underlying subscription is actually
  cancelled, which then follows the normal, safe downgrade path.

## Tax / VAT — unresolved launch decision

**No decision has been made.** This is a business/legal question requiring the
operator's own accounting/tax advice, not something to guess in code or documentation:

- Is MyKhaya's operating entity VAT-registered?
- Will [Stripe Tax](https://docs.stripe.com/tax) be used, or is tax handled another way?
- Are displayed customer prices tax-inclusive or tax-exclusive?
- What invoice/receipt information is legally required for the launch jurisdiction(s)?
- What is the geographical scope at launch (UK-only, or wider)?

**Until this is decided: do not enable live billing.** No "VAT included" or "plus
VAT" wording has been added anywhere in the product speculatively — Settings → Plan
& Billing and the public pricing page show exactly what Stripe returns, tax-neutral.
The code is already capable of reflecting whatever tax behaviour is eventually
configured in Stripe (Stripe Tax, if enabled, changes what `unit_amount`/displayed
price represents; MyKhaya's pricing display already just renders what Stripe
returns) — no MyKhaya code change is anticipated to be needed once the decision is
made, only Stripe-side configuration. If Stripe Tax is adopted, it would additionally
require collecting customer location/address at Checkout (Stripe's hosted Checkout
page can collect this itself, so likely no MyKhaya-side form is needed) and
verifying invoice emails include the required tax fields — assess this concretely
once the underlying decision is made, don't build for it speculatively now.

## Terms / Privacy / billing policy readiness

There is currently **no public Terms of Service or Privacy Policy page** in
MyKhaya (`apps/web/app`) and no dedicated legal-copy document under `docs/` — this
is a genuine gap, not merely undocumented. Before live billing, product/legal
material should explicitly address: the recurring nature of a Family subscription,
billing interval (monthly/annual), how to cancel, what happens on failed payment,
what happens on downgrade (data preserved, never deleted), how Complimentary access
works, and the refund/support approach documented above. **Do not fabricate this
wording** — it needs the same business/legal sign-off as the tax decision, and is
listed as a launch blocker below until it exists.

## Recurring billing wording (confirmed in place)

Checkout entry points (public pricing, onboarding plan step, Settings → Plan &
Billing) all state "Renews monthly until cancelled" / "Renews annually until
cancelled" next to the real provider-derived price — verified in Phases 4–5.
Cancellation state and the access-until date are shown accurately
("Cancels on DATE, keep access until then"). No dark patterns: monthly stays
equally selectable next to an annual "Best value" badge, Free is never
pre-obscured by a paid option.

## Dunning policy (confirmed, documented for launch)

- Stripe's own [Smart Retries](https://docs.stripe.com/billing/revenue-recovery/smart-retries)
  are the retry mechanism — MyKhaya runs no independent, competing payment-retry
  timer.
- A customer keeps Family access throughout `past_due` — there is no fixed
  "N days then downgrade" timer in MyKhaya; the transition to Free happens only
  once Stripe itself reports the subscription `canceled` (Stripe's retry schedule
  concluding, or a customer/operator explicitly cancelling).
- Customer messaging during recovery: Settings → Plan & Billing shows "Payment
  needs attention" with a direct link to the Customer Portal to update the payment
  method.
- Support expectation: an operator sees `past_due` in Platform Control Centre and
  can direct the customer to the Portal; no manual intervention is required for the
  system to behave correctly either way.

## Production go-live checklist

Do not execute the "Final" section automatically — every item requires a deliberate
human action outside normal deployment.

**Stripe account**: business account complete · identity/business verification
complete · bank/payout setup complete · public support details correct.

**Products/Prices**: live Family Product verified · live monthly Price created ·
live annual Price created · amounts/currency confirmed · tax behaviour confirmed
(see Tax/VAT above — must be resolved, not merely "confirmed as undecided").

**MyKhaya configuration**: live secret key configured · live webhook secret
configured · live Price IDs configured · `MYKHAYA_ENVIRONMENT=production` ·
`MYKHAYA_STRIPE_BILLING_CONFIGURED=true` · `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED`
**still false** during final validation.

**Webhook**: production endpoint registered · exactly the six required events
selected · a real signed test event delivered and confirmed processed (Stripe
Dashboard → send test webhook, or `stripe trigger` against the live endpoint using
Stripe's test-mode-safe trigger events where applicable).

**Portal**: production Portal configuration reviewed (payment method changes,
invoice visibility, cancellation policy, plan-switching **disabled** unless MyKhaya
explicitly supports monthly↔annual switching — it does not today, see "Portal
configuration" below).

**Commercial**: Terms/billing wording approved · VAT/tax decision approved and
configured · refund/support procedure approved (this document, reviewed by whoever
owns support).

**Technical**: migrations applied (`0023_billing_readiness` is head) · backup
confirmed working · reconciliation exercised against a real test Home · webhook
health confirmed via `GET /platform/subscriptions/webhook-health` · readiness
command (`billing-readiness.sh --check-stripe`) shows no `BLOCKER`.

**Final** (deliberate operator action, not automated):
1. Set `MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=true`, redeploy.
2. Optionally make one real, low-value test transaction if legally/operationally
   appropriate for this business, and verify it end to end.
3. Monitor `GET /platform/subscriptions/webhook-health` closely for the first
   period of real traffic.

## Portal configuration (production)

Configure the Stripe Customer Portal (Dashboard → Settings → Billing → Customer
Portal) to match what MyKhaya can actually reconcile:

- Payment method updates: **allow**.
- Invoice history: **allow** (MyKhaya deliberately builds no local invoice UI —
  the Portal is the entire experience for this).
- Subscription cancellation: **allow**, at period end (matches MyKhaya's documented
  `cancel_at_period_end` handling).
- **Plan/Price switching (monthly ↔ annual): disable in the Portal configuration**
  unless/until MyKhaya explicitly supports reconciling a Portal-initiated interval
  change — today, `apply_stripe_subscription_state` will correctly *reflect*
  whatever Stripe reports (interval, price) on the next webhook, so it wouldn't
  corrupt state, but the product experience (which interval a customer thinks
  they're on) hasn't been designed around a customer changing it from inside the
  Portal. Leave disabled until that's a deliberate product decision.
- Business information shown to the customer: your actual support
  email/name/branding, not MyKhaya placeholder values.
