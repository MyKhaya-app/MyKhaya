# Background Jobs

API requests should enqueue non-interactive work such as email, notifications, reminders and recurrence processing.

Important events use a transactional outbox so a committed database change cannot silently lose its downstream work. Workers use bounded retries, backoff, timeouts and failed-job visibility. Basic Redis Pub/Sub must not be used for durable business events.

Only one scheduler instance should be active at a time.
