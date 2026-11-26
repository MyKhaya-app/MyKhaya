# Driveway lookup-result reuse: technical design

Status: design only. This document does not enable result reuse.

## Boundary and purpose

The Add Vehicle preview and vehicle creation request remain separate provider
requests until this design receives explicit approval. A future implementation
may issue a short-lived server-side hand-off token so the create request can
reuse a preview result without trusting browser-supplied vehicle data.

## Proposed protocol

1. The authenticated preview request is authorised against the selected home
   and receives a random, single-use nonce and a signed result envelope.
2. The envelope contains a keyed registration digest, home ID, user ID,
   provider/environment identifier, issued-at and expiry timestamps, a result
   version, and the nonce. It does not expose provider credentials.
3. The signature is an HMAC or asymmetric signature produced by a deployment
   secret kept server-side. The browser cannot create or alter an envelope.
4. The create request submits the opaque envelope. The server verifies the
   signature, exact home/user binding, expiry, provider/environment, nonce
   uniqueness and the current registration. It then re-authorises household
   manage capability before saving.
5. Provider fields are still applied with the existing non-destructive merge
   rules. The current database row is locked and the registration is compared
   again immediately before commit.

## Replay, retention and abuse controls

- Expiry should be no longer than five minutes and should include a small clock
  skew allowance. The nonce is atomically consumed in Redis; reuse fails.
- No permanent enquiry history or arbitrary-registration result cache is
  created. Redis entries contain only the minimum opaque binding and expire
  automatically at the envelope deadline.
- Registration values are never used in Redis keys or logs; use a keyed digest
  for binding and aggregate audit events only.
- Existing per-user/provider rate limits, deployment-wide DVLA budget,
  per-vehicle lock and failure backoff remain in force.
- Payload size, malformed-token, replay and invalid-signature responses are
  generic and must not disclose whether a registration exists.

## Security and integrity tests required before implementation

- forged, modified, expired, wrong-user and wrong-home envelopes fail;
- a valid envelope cannot be replayed or transferred to another registration;
- membership removal between preview and create is enforced;
- provider/environment changes invalidate the envelope;
- Redis failure fails closed for token consumption;
- result data never bypasses encrypted-field or non-null preservation rules;
- no credentials, VIN, full registration or provider response appears in logs,
  audit metadata or frontend responses beyond existing authorised fields.

Implementation requires explicit approval after review of this boundary.
