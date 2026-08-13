"""Stripe billing (Phase 3) — MyKhaya's first real paid billing provider.

Stripe is a provider, not the entitlement engine: this package only ever
mutates HomeSubscription's provider/status/period/price fields and writes
HomeSubscriptionEvent rows. mykhaya.entitlements remains the single
authoritative resolver of what a Home can actually do — nothing in this
package, or anywhere else, asks Stripe directly whether a feature is
available. See docs/architecture/commercial-entitlements.md.
"""
