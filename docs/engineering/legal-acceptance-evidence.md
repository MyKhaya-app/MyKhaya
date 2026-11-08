# Legal acceptance evidence

MyKhaya keeps `LegalAcceptance` as the immutable legal-history record. A
qualifying adult acceptance or guardian authorisation also creates one
`LegalAcceptanceEvidence` snapshot in the same PostgreSQL transaction. The
snapshot stores the exact published markdown, its SHA-256 hash, the acceptance
reference, UTC timestamp, configured user timezone, trusted-proxy-resolved IP
when available, platform, action type and registered email/name at the time.

The transaction adds a deduplicated `legal.acceptance_evidence` outbox event.
The worker generates a PDF from the snapshot, archives it under the private
`legal_evidence_storage_dir`, records the PDF hash, and queues the mandatory
`legal_acceptance_confirmation` notification through the existing Notification
Engine and PCC template registry. The archived PDF is reused on retries and
PCC resends; it is never regenerated over the original key.

Email delivery supports a PDF attachment and records the SMTP `Message-ID` as
the provider message identifier. Evidence states distinguish generation,
queued/sending, sent, retry-pending and failed. Delivery is idempotent through
the evidence outbox dedupe key and notification delivery idempotency key.
Only users with a verified registered email receive the confirmation. Email
preferences cannot suppress this mandatory transactional message.

PCC support operators can see evidence/email state and authenticated operators
can download a private PDF or queue a separately audited resend. Historical
acceptances without an evidence row remain explicitly unavailable; no
historical evidence or delivery is fabricated.

## Acceptance entry points

Evidence is queued for every new adult legal record created by password signup,
browser Apple signup completion, browser Google signup completion, native
external-provider signup completion, the public legal acceptance/re-acceptance
endpoint, and Founding Beta enrolment when the current Beta Terms are accepted.

Guardian authorisation uses the same evidence flow for the guardian's recorded
authorisation. Child notice acknowledgement remains a separate passive notice
record and intentionally does not generate an adult legal certificate or email.
All paths use the same transactional outbox topic and immutable snapshot helper,
so a retry cannot create a second evidence record for one acceptance.

## Security and operations

PDF storage is not public and download routes require PCC roles and verify the
requested user/evidence relationship. Client IP capture uses the existing
trusted-proxy resolver; spoofed forwarding headers are not trusted. Document
content is copied from the immutable version row, not re-read from today's
published document. Retention follows the existing legal/privacy retention
configuration; this feature does not invent a statutory retention period.

Local validation must use synthetic users and a mock SMTP/Mailpit transport.
Do not deploy these migrations or enable real delivery against live DEV/PROD
without separate release approval.

## Validation and recovery

Run the focused local checks with:

```text
python -m pytest -q apps/api/tests/test_legal_acceptance_evidence.py --no-cov
ruff check --no-cache apps/api/mykhaya apps/api/tests/test_legal_acceptance_evidence.py
```

Frontend validation must run from an isolated copy of the dirty checkout when
the repository contains nested `.worktrees` directories. Exclude `.git`,
`.worktrees`, existing `node_modules` and `.next` output from the copy, then
install with the repository's supported Node.js/pnpm versions. The web checks
are:

```text
pnpm --filter @mykhaya/web exec vitest run app/control-centre/legal/acceptance/page.test.tsx --passWithNoTests
pnpm --filter @mykhaya/web exec tsc --noEmit --pretty false
pnpm --filter @mykhaya/web exec eslint app/control-centre/legal/acceptance/[id]/page.tsx
pnpm exec prettier --check --end-of-line crlf apps/web/app/control-centre/legal/acceptance/[id]/page.tsx
pnpm --filter @mykhaya/web build
```

Use `--no-frozen-lockfile` only in the disposable validation copy if the
workspace lockfile is already behind an unrelated package manifest; never
rewrite the original checkout's lockfile for this validation. The isolated
copy must retain all uncommitted legal-evidence files and must not include
nested worktree dependency trees.

The supported integration runner is
`infrastructure/scripts/run-tests.sh`. It builds and runs the isolated
`postgres-test`, `redis-test` and migration services from `compose.test.yml`,
then removes those disposable services and volumes. It must be used before a
controlled DEV rollout; the persistent development database is not a test
database.

If PDF generation succeeds but email delivery fails, the archived PDF and
immutable evidence row remain available. Temporary SMTP failures set the row
to retry-pending and follow the worker backoff policy; permanent failures are
recorded as failed with a sanitised error. Operators may use the authenticated
PCC resend endpoint after verifying the recipient and evidence reference. The
resend idempotency key is stable per evidence row, so repeated requests do not
queue duplicate deliveries.
