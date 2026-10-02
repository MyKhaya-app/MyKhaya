# Central platform logging

MyKhaya's central syslog integration is a platform-only observability feature.
It is disabled by default and is configured by authorised Platform Control
Centre administrators. The API, worker and scheduler attach the same bounded,
best-effort dispatcher to the existing `structlog` pipeline; browser clients
never connect to the destination.

Events are emitted as RFC 5424 messages with a `mykhaya@32473` structured-data
element containing the environment, service and existing structured fields.
UDP, TCP and TLS transports are supported. TLS verifies certificates by
default. Delivery is asynchronous, bounded, and non-recursive: a full queue,
timeout, malformed destination or network failure cannot block a request or
create another log event. A recorded delivery means the configured transport
completed its send operation; it does not claim that a remote collector stored
the message.

The queue has a hard 1,000-event limit and exposes a dropped-event counter in
PCC status. TCP/TLS sends have connection, drain and close timeouts; events are
not retried in a tight loop. The configured hostname is intentionally allowed
to target private Graylog networks. This is a trusted administrator-controlled
server-side egress path, not a general user-controlled URL fetcher; host,
protocol, port and control-character validation prevent malformed transport
inputs, while network policy remains the deployment's responsibility.

The formatter applies recursive redaction before forwarding. Passwords,
tokens, cookies, authorisation headers, API keys, private keys and comparable
secret-bearing fields are replaced with `[REDACTED]`, including nested values.
Credential patterns in exception text are scrubbed as well. Personal fields
such as email addresses, names, notes, descriptions, support content, vehicle
registrations and uploaded filenames are excluded from the external stream;
the existing database audit records retain their established behaviour.
Audit events are still persisted in the existing audit tables and are also
represented in the central structured stream without exposing secret values.
The destination settings and test endpoint are protected by the existing PCC
roles and recent-auth requirements.
