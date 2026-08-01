# Feature Flags

Feature flags keep unfinished modules unavailable without relying on navigation alone. The authoritative evaluator is `mykhaya.features.is_feature_enabled`.

Evaluation order is:

1. Home override, when one exists.
2. Global flag.
3. Disabled for a missing or unknown flag.

The catalogue contains `calendar`, `tasks`, `shopping`, `meals`, `plans`, `wish_lists`, `notifications` and `external_sharing`. Migration `0004_feature_flags` creates every flag disabled. Calendar code is retained but its API returns an indistinguishable 404 and its UI redirects home until the flag is enabled.

Normal users may read evaluated availability for their own Home. Only permitted Control Centre operators can change global or Home values. Mutations require recent authentication, explicit confirmation and a reason, and every change is written to the dedicated administrative audit trail.

Every future module must call the central server-side evaluator at its API boundary. Client navigation is only a secondary presentation control.
