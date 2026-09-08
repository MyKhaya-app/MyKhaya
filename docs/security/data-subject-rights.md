# Data-subject Rights

MyKhaya must support authenticated, verified workflows for access, export, correction, restriction, objection, erasure and account closure. Requests require identity verification, request logging, deadline tracking, processor coordination, exception/legal review, secure delivery and completion evidence.

Current account profile correction is limited. Export, restriction, objection and full closure workflows are designed requirements, not implemented capabilities. Operators must not improvise hard deletion or email replacement through the database.

## Erasure: current capability

A narrow, PCC-operator-only erasure capability exists and is documented in full in [data-retention.md](./data-retention.md#control-centre-lifecycle-and-minimisation-actions):

- **User anonymisation** overwrites a User's direct identifying fields (name, email, avatar, birth date) and permanently revokes their authentication credentials and devices, once the account has first been Archived. It is the closest capability to "erase my personal data" the product currently offers. It is not a full account deletion: the `User` row and historical household content the person created are retained (structurally required, and to avoid corrupting other members' shared history), and it cannot be undone.
- **Permanent Home deletion** hard-deletes a Home, but only when it is Archived and holds no household history — no calendar/routine/reminder/list/wishlist content, no membership beyond the Home's own creator, and no billing history. It exists for discarding accidental or disposable test Homes, not for closing an in-use household account.

Both require administrative authorisation, recent re-authentication, a documented reason and a typed confirmation, and are always single-record actions — no bulk erasure exists.

This is **not** a complete, self-service, statutory erasure workflow: there is no user-facing "delete my account" flow, no automated processor/backup coordination, no deadline tracking, and no support for erasing a populated Home or a User who has not first been Archived. A DSR erasure request today must still be actioned by an operator following this narrow capability plus manual review of what it does not cover, and a full erasure workflow (export, restriction, objection, populated-Home closure, backup expiry) remains a designed requirement, not an implemented one.

Future exports must be Home-scoped, avoid exposing another person's private data, and handle parent-managed child information. A future complete erasure workflow must cover primary data, derived records, processors and backup expiry while retaining only lawfully required audit evidence.
