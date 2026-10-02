# Platform Administration Scope

Version one operates the hosted MyKhaya service through operational metadata, health, jobs, mail identity, Stripe payment configuration, typed settings, feature availability, security events, audit, administrators and public incidents.

It excludes impersonation, private household-content browsing, unsafe deletion, ownership transfer, commercial pricing/plan decisions, marketing analytics and product modules. Configuring *how* Stripe connects (keys, webhook secret, Price IDs, Test/Live mode) is in scope via the Payments settings page; deciding *what* MyKhaya charges, and the commercial Free/Family entitlement model itself, are not — see `docs/architecture/commercial-entitlements.md`. Parent-managed child profiles are the initial position. They are not login accounts; child data is minimised and private by default. Location tracking and external communication by child profiles are prohibited in this scope.

The Control Centre is not production-ready until mandatory hardware-backed MFA and the documented production blockers are closed.
