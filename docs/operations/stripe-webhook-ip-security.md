# Stripe webhook IP security

The PCC setting is environment-local: DEV and PROD each keep their own policy,
trusted list, sync timestamps and blocked-request counters. The application never
changes NetBird or Caddy configuration automatically.

MyKhaya downloads Stripe's official webhook feed from
`https://stripe.com/files/ips/ips_webhooks.json` at most once every 24 hours. The
download is accepted only when it is valid JSON containing a bounded list of public
IP addresses. A failed refresh retains the last known-good list and records a safe
error for PCC operators.

The default mode is **Monitoring only**. Requests are observed using the same
trusted-proxy boundary as the rest of the API, but are not blocked. Enforcement
should only be enabled after `MYKHAYA_TRUSTED_PROXY_CIDRS` is verified to contain
only the Caddy addresses and the live proxy chain has been tested against spoofed
`X-Forwarded-For` headers.

Enforcement applies only to `POST /api/v1/billing/stripe/webhook`. A request is
resolved from the socket peer; `X-Forwarded-For` is considered only when that peer
is in the configured trusted-proxy CIDRs. Direct backend requests and spoofed
forwarded headers therefore cannot claim a Stripe address. Stripe signature
verification remains mandatory for every request that passes the IP policy.

If enforcement has no fresh last-known-good list, the webhook returns HTTP 503 and
does not process the event. This is deliberate: it avoids silently accepting traffic
when the operator has explicitly enabled enforcement. Return to Monitoring only,
refresh the feed, verify the proxy trust configuration, then re-enable Enforcement.

## Live DEV recovery

On the real DEV server, first inspect the deployment and proxy logs:

```sh
docker compose -f compose.yml -f compose.dev.yml ps
docker compose -f compose.yml -f compose.dev.yml logs --since 2h caddy api
```

Use PCC → Subscriptions → Stripe Webhook Security to confirm the mode, trusted IP
count, last successful update, stale/error state and blocked counts. Do not copy a
Stripe secret into a command or log.

While still in Monitoring only, send a harmless request with a deliberately spoofed
forwarded header directly through the public DEV hostname and confirm the API logs
the socket peer rather than the spoofed value. Then resend one Stripe Test-mode
delivery from the Stripe Dashboard and confirm the event ID reaches the API and is
recorded in `stripe_webhook_events`.

Only after those checks should an authorised operator enable Enforcement. If genuine
Stripe deliveries are blocked, immediately switch back to Monitoring only, refresh
the official feed, correct the trusted proxy CIDRs or proxy chain, and retry the
failed Test-mode deliveries from Stripe. Never bypass signature verification or
manually insert webhook rows to recover an event.
