# Plans and Pricing

MyKhaya's commercial model (see `docs/architecture/commercial-entitlements.md` for the technical design across Phases 1–3). This document describes product-facing plan shape; pricing figures here are product configuration, not embedded backend logic — nothing in `mykhaya.entitlements` hardcodes a price, only capability booleans and limits. As of Phase 3, the Family figures below are also the actual configured Stripe Prices in test mode — see "Phase 3: Stripe billing" below for what that means and doesn't mean yet.

## Free — £0

The default for every new Home. One Home, one calendar. Fully and indefinitely useful — Free is not a time-limited trial and is not deliberately crippled to pressure an upgrade. A family that never upgrades should still find MyKhaya worth using every day.

## Family — £3.99/month or £39/year

Full household access: unlimited calendars per Home (in practice, whatever a future multi-calendar feature allows), and every module gated behind the `family` plan as those modules ship (Lists, Chores, Notes, Wish Lists are defined as Family-gated capabilities already, ready for when those modules exist). Billed per Home, not per person — everyone in the Home benefits once the Home is on Family, regardless of who pays. As of Phase 3 this is a real, configured Stripe Price (in Stripe test mode) rather than only a documented intention — see below. The *actual* amount charged always comes from Stripe at runtime (`mykhaya.billing.pricing`), never from this document or any code constant, so a future price change is a Stripe Dashboard + two environment variables change, not a code change.

## Complimentary Family access

An admin-granted Family-equivalent plan for beta testers, friends and family, or goodwill access — not a disguised free Stripe subscription. Granted and revoked only by a Platform Control Centre operator, with a required reason and an optional expiry date. Used for MyKhaya's own beta programme and similar controlled early access, not intended as a general promo/coupon mechanism (promotional codes remain explicitly out of scope — see "Explicitly out of scope for Phase 3" in the architecture doc — if ever built, that's a later phase's concern).

## What Phase 1 does not include

No payment collection of any kind — no card form, no Stripe Checkout, no in-app purchase. No pricing page on the public site or in the app. No payment step in the signup flow. No Plan & Billing management screen for households. A household on Free could not yet self-serve upgrade to Family in Phase 1 — the only way onto Family was a Platform Control Centre operator granting Complimentary access. Phase 3 (below) adds real self-serve Stripe Checkout, in test mode.

## Phase 2: the administrator-facing complimentary-access workflow

Phase 2 gives Platform Control Centre operators (support/administrator/owner roles) a proper working surface for the above, under a new **Subscriptions** area — still no payment collection, still no household-facing change.

- **Subscriptions overview**: summary counts (Total Homes, Free, Family, Complimentary, Expired complimentary, Past due, Cancelled) and a searchable/filterable table of every Home's stored and effective commercial state, so an operator can answer "which Homes are on Complimentary access" or "did this Home's trial expire" without querying the database directly.
- **Home commercial detail**: a single Home's full stored state (plan, provider, status, complimentary reason/note/expiry/who-granted-it), its currently effective state (which may differ, e.g. after expiry), its resolved entitlements in plain language ("Calendar maximum: 1", "Lists: Not available"), and its full commercial event history.
- **Grant complimentary Family access**: an operator picks a reason (a short preset list — Beta tester, Friends & Family, Internal testing, Partner, Promotional — or free text), an optional internal note (never shown to the household), and an expiry (Never, or a specific date), then confirms with a required reason for the administrative action itself. This is the same underlying grant used for MyKhaya's beta programme.
- **Remove complimentary access**: returns the Home to Free, with the consequence ("returns to Free plan entitlements; no data is deleted") shown before confirming.
- **Extending or making complimentary access permanent** reuses the same grant action with a new expiry — there is no separate "edit" flow, keeping every commercial-state change a single, well-defined, audited action rather than a free-form edit.

The £0/£3.99/£39 figures shown throughout this Subscriptions area are the same read-only informational figures as above — a label for operators to understand plan intent, not a price an operator can change from the UI. As of Phase 3, for a Stripe-backed Home, the Home commercial detail view additionally shows the *actual* amount that specific Home is billed, resolved live from Stripe — which may differ from the current headline price if the Home is on an older, grandfathered Price (see "Price increases and grandfathering" in the architecture doc).

## Phase 3: Stripe billing (test/sandbox mode)

Family becomes purchasable through Stripe Checkout — **in Stripe test mode only**; no real payment is ever taken by this phase, and live billing is explicitly not enabled. A Home Admin can, from a minimal `/settings/billing` page:

- See the Home's current plan, provider, status, and (once on Family) renewal/cancellation date.
- Start Checkout for monthly or annual Family, at the real price read live from Stripe.
- Open the Stripe Customer Portal to manage payment details.

**What actually grants Family access** is Stripe confirming the subscription is genuinely active — never the browser returning from Checkout. A customer who completes payment sees "Payment received. We're confirming your subscription" and the page updates once MyKhaya's backend has verified it via Stripe's own webhook — usually a few seconds, never instant by design (see "Checkout lifecycle" in the architecture doc for why).

**`past_due` policy**: a single missed renewal does not remove Family access. The customer keeps everything while Stripe retries the payment automatically and while they can fix their payment method via the Customer Portal; access is only lost once Stripe's own retry schedule concludes and the subscription is genuinely cancelled.

**Cancellation**: cancelling (via the Customer Portal) schedules the subscription to end at the current paid period's close — the Home keeps Family access until then, exactly like any other subscription product. Once the period ends, the Home returns to Free. No Home data — calendars, events, members, anything — is ever deleted by a cancellation, at any point in this flow.

This phase deliberately does not include: the public marketing site's pricing page, a payment step during signup, or the polished household Plan & Billing experience — `/settings/billing` is a minimal, functional surface built to prove the underlying billing plumbing works end to end, not the finished product page.

## Phase 4: the household Plan & Billing experience

`/settings/billing` becomes the finished product page — still in Stripe test/sandbox mode, still no real payment taken. Any adult member of a Home can open it and see the Home's plan status; only a Home Administrator (or anyone else with `billing_manage`) sees the buttons to actually change anything.

**Free**: "Your Home is currently using MyKhaya Free," with an invitation to upgrade to Family. A Home whose complimentary access or Stripe subscription has since ended is shown as Free too, but with a short explanation of what happened ("Your complimentary Family access ended on DATE" / "Your Family subscription ended on DATE") rather than looking identical to a Home that was never on Family — and a reassurance that no Home data was deleted.

**Family upgrade flow**: a Free Home eligible to self-serve sees Monthly and Annual options, each showing the real price read live from Stripe at the moment the page loads — never a number written into this document or the app's code. When Stripe's own configured prices make the annual option genuinely cheaper per year than paying monthly twelve times, it's marked "Best value" and shows the amount saved; when it isn't (or can't be calculated), no badge is shown and no saving is invented. Starting Checkout hands off to Stripe's own payment page — MyKhaya never sees or stores a card number. Returning from Checkout shows "Payment received. We're confirming your subscription" until the backend has verified it via Stripe's own confirmation — normally a few seconds, and refreshing the page always shows the true current state.

**Complimentary Family access** (admin-granted, see Phase 2) is shown as Family with a "Complimentary access" label instead of a price, either "Access does not expire" or "Access until DATE" depending on whether an expiry was set.

**A live paying Family subscription** shows Monthly or Annual, the actual amount currently charged (which may be an older, grandfathered price — see the architecture doc), and the renewal date. A "Manage billing" button opens Stripe's own Customer Portal for payment method and invoice details — MyKhaya does not build or store any of that itself.

**A payment problem** ("Payment needs attention") is shown clearly but calmly — the Home keeps its Family access while Stripe automatically retries, and the button becomes "Update payment method," taking the member straight to the Customer Portal to fix it.

**A cancelled-but-not-yet-ended subscription** shows "Cancels on DATE, keep access until then" — access continues exactly as paid for until that date, then the Home returns to Free with nothing deleted.

Throughout, the page only ever compares Free and Family on things that actually exist today — currently just calendars per Home — never lists or advertises a module (Lists, Chores, Notes, Wish Lists, and similar) that is defined in the commercial model for a future release but isn't actually available to use yet, so nothing on this page over-promises.

**What Phase 4 still does not include**: the public marketing site's pricing page, a payment step during signup, promotional codes, and any plan other than Free and Family — all remain out of scope for a later phase.
