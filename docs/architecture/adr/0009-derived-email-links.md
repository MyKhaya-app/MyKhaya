# ADR 0009: Derived Email Links and Identifier-Only Jobs

**Status:** Accepted

Verification, reset and invitation links are deterministic authenticated encodings of a UUIDv7 record identifier and purpose. The database stores only a keyed hash. Outbox payloads and Redis jobs contain identifiers, never reusable links. The worker reconstructs a link immediately before email delivery.

This preserves recoverable outbox delivery without persisting reusable secrets in queue payloads, logs or audit records. Consumption remains transactional and replay is denied.
