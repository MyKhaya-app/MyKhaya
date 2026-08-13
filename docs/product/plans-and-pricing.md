# Plans and Pricing

MyKhaya's commercial model, as of Phase 1 of the commercial architecture (see `docs/architecture/commercial-entitlements.md` for the technical design). This document describes product-facing plan shape; pricing figures here are product configuration, not embedded backend logic — nothing in `mykhaya.entitlements` hardcodes a price, only capability booleans and limits.

## Free — £0

The default for every new Home. One Home, one calendar. Fully and indefinitely useful — Free is not a time-limited trial and is not deliberately crippled to pressure an upgrade. A family that never upgrades should still find MyKhaya worth using every day.

## Family — £3.99/month or £39/year

Full household access: unlimited calendars per Home (in practice, whatever a future multi-calendar feature allows), and every module gated behind the `family` plan as those modules ship (Lists, Chores, Notes, Wish Lists are defined as Family-gated capabilities already, ready for when those modules exist). Billed per Home, not per person — everyone in the Home benefits once the Home is on Family, regardless of who pays.

## Complimentary Family access

An admin-granted Family-equivalent plan for beta testers, friends and family, or goodwill access — not a disguised free Stripe subscription. Granted and revoked only by a Platform Control Centre operator, with a required reason and an optional expiry date. Used for MyKhaya's own beta programme and similar controlled early access, not intended as a general promo/coupon mechanism (that's a Phase 3 concern if it's ever built).

## What Phase 1 does not include

No payment collection of any kind — no card form, no Stripe Checkout, no in-app purchase. No pricing page on the public site or in the app. No payment step in the signup flow. No Plan & Billing management screen for households. A household on Free today cannot yet self-serve upgrade to Family; that arrives with the Stripe integration (Phase 3) and its accompanying UI (Phase 2 prepares the Platform Control Centre view; a household-facing billing UI is a later phase still). Until then, the only way onto Family is a Platform Control Centre operator granting Complimentary access.
