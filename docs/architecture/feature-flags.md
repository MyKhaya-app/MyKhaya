# Feature Flags

Feature flags keep unfinished modules unavailable without relying on navigation alone. The authoritative evaluator is `mykhaya.features.is_feature_enabled`.

## Authority order (Phase 2A)

PCC platform availability is authoritative over a Home's own choice:

1. Hidden modules always fail closed, before anything else is consulted.
2. The global `FeatureFlag` — PCC's platform-wide switch — is checked next. When it is disabled (or has no row at all), the feature is disabled everywhere; **no Home override can re-enable it.**
3. Only once the platform allows a feature does a Home's `FeatureOverride` apply: `enabled=False` opts the Home out of something the platform allows; `enabled=True` opts back in (a no-op unless the platform had it off by default); no row means the Home simply inherits the platform's own state.

A lower layer can therefore only ever narrow access the platform has granted, never widen it beyond that. This corrected an earlier defect where a Home override checked *before* the global flag could bypass a platform-wide disable — see `mykhaya.features.platform_feature_enabled`/`is_feature_enabled` and `test_feature_precedence.py` for the full precedence-matrix coverage.

The module registry in `mykhaya.module_registry` is the product source of truth. Each module has a release state (`core`, `released`, `beta`, `early_access`, `internal`, `deprecated` or `hidden`), default state, version, dependencies, permissions and optional route. Core modules cannot be disabled. Released, beta and early-access modules may be enabled per Home by a Home Admin (subject to the platform switch above). Hidden modules are absent from household and platform catalogues, navigation and routes, and their server guards fail closed even if a stale database flag says they are enabled. `ModuleDefinition.home_admin_manageable` (default `True`) additionally controls whether a module is offered as a toggle on the Home Admin Module Management screen at all — `False` for Notifications (core platform delivery infrastructure, never a user-disableable module) and External sharing (a Calendar capability, not a standalone module); their `FeatureFlag`/`FeatureOverride` rows and `is_feature_enabled` evaluation are otherwise unaffected, and Platform Control Centre's global module controls still cover both.

The current registry exposes Dashboard, Household members and Security as core modules; Calendar, Lists (`shopping`), Meal Plans (`meals`), Wishlists (`wish_lists`) and Nudges (`nudges` — Routines, Reminders and To-dos) as released, Home-Admin-toggleable modules; External sharing as beta; and Tasks and Plans as hidden (retired/not-yet-built). Migration `0004_feature_flags` seeded every key's disabled database record for forward compatibility; `0046_notifications_module_released`, `0062_nudges_feature_flag_seed` and `0063_feature_flag_backfill` subsequently promoted Notifications, Nudges, Calendar, Lists, Meal Plans and Wishlists to enabled=true globally, matching their released status — registration into the enum alone never makes a module accessible on its own.

Nudges (Routines/Reminders/To-dos) gates on its own `FeatureKey.nudges` — not `FeatureKey.notifications`. Notifications remains a separate, independent check made by the notification *delivery* worker (e.g. `mykhaya.notifications.routines`/`standalone_reminders`) when it decides whether a specific reminder push/email can be sent; disabling the Nudges module never disables Notifications, and disabling Notifications never disables the ability to create/edit/complete a Routine, Reminder or To-do.

Home changes require the `features.manage` capability, an explicit confirmation and an audit reason. Dependencies are enabled first; a module with enabled dependants cannot be disabled; enabling a module whose dependency (or the module itself) is currently disabled at the platform level is rejected outright rather than writing a Home override that would have no effect. Disabling a module preserves its data.

Normal users may read evaluated availability for their own Home. Only permitted Control Centre operators can change global values; Home Admins change their own Home's override. Mutations require recent authentication, explicit confirmation and a reason, and every change is written to the dedicated administrative audit trail.

Every future module must call the central server-side evaluator at its API boundary. Client navigation is only a secondary presentation control.
