# Background Jobs

API requests should enqueue non-interactive work such as email, notifications, reminders and recurrence processing.

Important events use a transactional outbox so a committed database change cannot silently lose its downstream work. Workers use bounded retries, backoff, timeouts and failed-job visibility. Basic Redis Pub/Sub must not be used for durable business events.

Only one scheduler instance should be active at a time.

Worker and scheduler processes write safe operational heartbeats for the privileged health view. They do not expose worker names, queue depth or scheduler state through public status. Manual retries remain disabled until job-type idempotency and retryability are explicitly registered.
