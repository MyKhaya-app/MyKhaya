# Khaya Control Centre

The Khaya Control Centre is the household administration area at `/khaya-control-centre`. It is not the platform operator Control Centre at `admin.mykhaya.app`. Only a membership with the Home Admin capability profile can use its APIs; client-side hiding is convenience, not authorization.

Implemented sections cover members and relationships, managed Child profiles, security links and Feature Management. Relationship changes, child controls and feature changes require a meaningful reason, explicit confirmation and an audit record.

## Relationship and permission model

- Home Admin: household settings, relationships, children, security and feature management. The final Home Admin is protected.
- Partner: normal household Calendar collaboration without administration.
- Child: distinct managed profile, explicit guardians and deny-by-default controls.
- Extended Family and Friend: no broad household access; resources such as Calendar must be shared explicitly.

Relationship is descriptive. Permission profiles and capabilities are authoritative and may be extended by explicit, audited overrides without changing the personal relationship.

## Child lifecycle and privacy

Creation asks only for display name, age band and at least one responsible adult. It does not collect full date of birth or issue an adult invitation. Defaults deny Calendar, location, chat, uploads, documents and external sharing. Home Admins can review permissions, guardians and age bands individually. Starting an adult transition records a review-due state and grants nothing automatically. Profile removal anonymises identifying data and revokes access.

Any later adult-account conversion must verify ownership of a new adult email address before granting permissions; the review-due state is intentionally not an automatic conversion.

## Module lifecycle

Feature Management lists only core, released and beta modules from the server registry. Core modules are always on. Released modules may be toggled by Home Admins. Beta modules must be clearly labelled and default off. Hidden modules have no visible route or API catalogue entry. Disabling a module preserves its records so re-enabling is safe.
