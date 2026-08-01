# Platform Health

Internal health uses Healthy, Degraded, Unavailable and Unknown. Each observation includes an explanation, check time, last success where known and a safe operator action. Unknown is the correct state when no authoritative observation exists.

PostgreSQL and Redis are actively checked. Worker and scheduler state use database heartbeats. Backup freshness, restore tests, migration drift, disk capacity, mail transport, response time and error rate require deployment integrations and currently report Unknown or remain explicitly unavailable. Never expose internal health through the public status API.
