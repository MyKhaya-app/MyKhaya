# ADR 0007: Transactional Outbox and Redis Job Queue

**Status:** Accepted

Business writes and their outbox records commit in one PostgreSQL transaction. A single scheduler claims pending outbox rows with `SKIP LOCKED` and enqueues idempotent jobs into Redis. Workers use bounded retries, exponential backoff and PostgreSQL job records for visibility. Redis is coordination infrastructure, not the source of truth; an interrupted enqueue leaves the outbox row eligible for retry.

