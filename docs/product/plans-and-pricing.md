# Plans and Pricing

MyKhaya's commercial model (see `docs/architecture/commercial-entitlements.md` for the technical design across Phases 1–3). This document describes product-facing plan shape; pricing figures here are product configuration, not embedded backend logic — nothing in `mykhaya.entitlements` hardcodes a price, only capability booleans and limits. As of Phase 3, the Family figures below are also the actual configured Stripe Prices in test mode — see "Phase 3: Stripe billing" below for what that means and doesn't mean yet.

## Free — £0

The default for every new Home. One Home, one calendar. Fully and indefinitely useful — Free is not a time-limited trial and is not deliberately crippled to pressure an upgrade. A family that never upgrades should still find MyKhaya worth using every day.

## Family — £3.99/month or £39/year

Full household access: unlimited calendars per Home — a real, usable feature as of Phase 6 (see below) — and every module gated behind the `family` plan as those modules ship (Lists, Chores, Notes, Wish Lists are defined as Family-gated capabilities already, ready for when those modules exist). Billed per Home, not per person — everyone in the Home benefits once the Home is on Family, regardless of who pays. As of Phase 3 this is a real, configured Stripe Price (in Stripe test mode) rather than only a documented intention — see below. The *actual* amount charged always comes from Stripe at runtime (`mykhaya.billing.pricing`), never from this document or any code constant, so a future price change is a Stripe Dashboard + two environment variables change, not a code change.

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

## Phase 5: public pricing and signing up

MyKhaya's public homepage now has a pricing section, and a new visitor gets to choose a plan as part of creating their account — the two things Phase 4 deliberately left out.

**On the homepage**: two cards, Free and Family, side by side. Free reads simply — "1 calendar, core MyKhaya experience, no payment details required, £0." Family shows the real current monthly and annual price (never a number written into this app's code — see the architecture doc), a Monthly/Annual switch, and, only when it's genuinely true, a "Best value" badge on the annual option with the amount saved. Underneath, a short Free vs Family comparison, sourced from the same plan definitions the Settings page already uses — so the homepage can never say something different from what a signed-in Home actually sees. If Family pricing can't be loaded (Stripe temporarily unavailable), the page says so plainly and Free signup stays fully available — the homepage never crashes, never shows a stale price, and never blocks anyone from starting for free.

**Choosing a plan is a hint, not a purchase.** Whether someone picks Free or Family on the homepage, the very next thing that happens is ordinary account creation — the same email, name and password form as always. Nothing about payment is asked yet, and nothing about the plan choice can itself unlock Family; it's only carried forward so the next screen knows what to suggest.

**Creating your Home always starts on Free.** Every new Home is created the same way it always has been — Free, no Stripe Customer, no payment prompt — regardless of what was picked earlier. Immediately after, a short "How would you like to use MyKhaya?" step offers Free (just continue) or Family (choose Monthly or Annual, see the live price, and go to Stripe Checkout). Someone who arrives straight at the signup page, without ever visiting the homepage, gets exactly the same choice — it isn't a homepage-only feature.

**Family at signup uses the exact same Checkout as Settings → Plan & Billing.** There's no separate "signup checkout" — it's the same Stripe handoff, the same "we're confirming your subscription" message on return, and the same rule that a browser redirect is never, by itself, proof of payment. Family access only ever turns on once Stripe's own confirmation has been received.

**If Checkout doesn't finish** — the visitor closes the tab, payment fails, Stripe is briefly unavailable, or they simply come back another day — nothing is lost and nothing is broken. Their account and Home are already fully valid and already on Free. They can carry on using MyKhaya normally, and upgrade whenever they like from Settings → Plan & Billing. Nobody is shown an error, made to feel like something went wrong, or funnelled back into Checkout on every subsequent sign-in.

**Someone joining an existing Home through an invitation never sees a plan choice at all.** The Home's plan belongs to the Home, not to each person who joins it — an invited member simply joins and starts using whatever plan that Home is already on.

**One subscription for the whole Home, never wording that suggests a per-person price.** This is said plainly wherever Family is described, on the homepage and in signup alike.

**What Phase 5 still does not include**: Apple/Google in-app billing, promotional or discount codes, any plan beyond Free and Family, and live (real-money) billing — all remain deliberately out of scope for a later phase.

## Phase 6: what Free and Family actually mean for Calendar

Free and Family calendars now genuinely behave differently — this was previously just a number on a pricing page.

**Free — one calendar, fully usable.** A Free Home has exactly one calendar and can use it completely normally: create, edit, delete events, invite members, set reminders — nothing about it feels limited or trial-like. Free was never meant to feel broken, and it doesn't.

**Family — add calendars as you need them.** A Family Home can create as many calendars as it wants — one for the household, one for work, one for the kids' activities, whatever suits. Every calendar behaves identically; there's no "main" calendar that's more capable than the others.

**Trying to add a second calendar on Free** shows a plain explanation — "Multiple calendars are included with MyKhaya Family" — with a link to see the Family plan. No price is shown there; that lives on Plan & Billing, where it's always current.

**If a Home downgrades from Family to Free while it has more than one calendar** (a subscription ending, complimentary access expiring), nothing is deleted. Every calendar and every event stays exactly where it was. One calendar — the household's original one — keeps working normally. The others become read-only: still fully visible, still showing all their events, but new events can't be added to them and existing ones can't be changed or removed individually, until either the Home upgrades back to Family or the calendars are removed outright (which the Home can always choose to do). Settings → Plan & Billing explains this plainly if it applies: "Your Home has 3 calendars. The Free plan includes 1. Your calendars and events are safe. Upgrade to Family to restore full access to all calendars."

**Upgrading back to Family restores everything immediately** — every previously-read-only calendar becomes fully usable again the moment the upgrade takes effect, automatically, with nothing to request or wait for.

**None of this ever affects signing in, viewing your Home, managing your account, or security settings** — a Home over its Free calendar limit is never locked out of anything except adding to or editing the calendars beyond its plan.
