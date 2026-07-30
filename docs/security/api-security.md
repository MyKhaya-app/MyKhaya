# API Security

Every endpoint must define authentication, authorised roles, Home resolution, accepted and returned fields, rate-limit class, idempotency, audit needs and resource limits.

Explicitly address OWASP API Security Top 10:2023, especially object-level and property-level authorisation, authentication, function-level authorisation, resource consumption, sensitive business flows, SSRF, configuration, inventory and third-party API handling.

Never bind unrestricted persistence models to request bodies. Cross-Home tests are required for every Home-owned resource.
