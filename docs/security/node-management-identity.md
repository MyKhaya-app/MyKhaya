# Node Management Identity — Phase 0 Contract

This is a design contract only. No certificate, registration or authentication runtime has been added.

## Bootstrap and mTLS

Node registration uses a short-lived, single-use bootstrap token created by an authorised PCC operator. The token is bound to the intended node ID, environment and Region, is stored hashed, expires quickly, and is invalid after successful exchange or explicit revocation. It is never used for normal heartbeats.

The exchange occurs over TLS and returns a unique node certificate/private key pair or a CSR-based certificate issued by the approved MyKhaya node CA. The private key is generated and retained on the node. Subsequent management calls require mTLS with the node certificate; the token is not accepted as a fallback credential.

There is no reusable PKI service in the current repository. `apps/api/mykhaya/secrets_crypto.py` protects application secrets but is not a CA. Phase 1 therefore requires an explicit CA/key custody decision before implementation; it must not silently repurpose application encryption keys.

## Certificate lifecycle

Certificates have short bounded lifetimes and carry only node identity, environment and Region claims. Rotation is an authenticated node action with overlap for the current certificate. Revocation is recorded in the PCC audit trail and enforced by the management API. Lost/compromised credentials are revoked before replacement. Registration tokens, node private keys and CA private material must never be logged or returned by PCC list/detail APIs.

## Authorisation and audit

PCC operator authorisation continues through `platform_security.py` and existing role/recent-auth/CSRF/MFA controls. Node management endpoints use a dedicated permission if the existing PCC permission framework can support it cleanly; otherwise they remain inside the existing operator boundary with an explicit audit reason. Every issue, rotate, revoke, heartbeat anomaly, placement change and destructive managed-record action is auditable through the existing platform audit models/services.

PCC may know node directory metadata and health, but must not use node credentials to access a regional PostgreSQL database. No SSH, remote shell, arbitrary command execution or NetBird dependency is permitted.

