# Feature Flags

Feature flags keep unfinished modules unavailable without relying on navigation alone. The authoritative evaluator is `mykhaya.features.is_feature_enabled`.

Evaluation order is:

1. Home override, when one exists.
2. Global flag.
3. Disabled for a missing or unknown flag.

The module registry in `mykhaya.module_registry` is the product source of truth. Each module has a release state (`core`, `released`, `beta` or `hidden`), default state, version, dependencies, permissions and optional route. Core modules cannot be disabled. Released and beta modules may be enabled per Home by a Home Admin. Hidden modules are absent from household and platform catalogues, navigation and routes, and their server guards fail closed even if a stale database flag says they are enabled.

The current registry exposes Dashboard, Household members and Security as core modules and Calendar as a released, opt-in module. Tasks, Shopping, Meals, Plans, Wish Lists, Notifications and External sharing remain hidden because their implementations are placeholders. Migration `0004_feature_flags` retains their disabled database records for forward compatibility; registration does not make them accessible.

Home changes require the `features.manage` capability, an explicit confirmation and an audit reason. Dependencies are enabled first; a module with enabled dependants cannot be disabled. Disabling a module preserves its data. The global platform switch supplies the default when a Home has no explicit override; the documented evaluation order above remains authoritative.

Normal users may read evaluated availability for their own Home. Only permitted Control Centre operators can change global or Home values. Mutations require recent authentication, explicit confirmation and a reason, and every change is written to the dedicated administrative audit trail.

Every future module must call the central server-side evaluator at its API boundary. Client navigation is only a secondary presentation control.
