# Legal & Compliance Phase 5 launch checklist

This is an internal operational checklist, not legal advice and not evidence
that MyKhaya is legally compliant. An authorised operator and appropriate
external advisers must complete the subjective/legal items before publication.

## Reconciliation findings

The repository supports private Home data, adult sessions/MFA, native bearer
sessions, managed-child login, guardian authorisation, child acknowledgement,
Calendar, Nudges, Meals, lists/Wishlists, manual Budget, Driveway/DVLA lookup,
support tickets, screenshots, optional diagnostics, push/email notifications,
Stripe subscriptions, audit records, local logs and operator-configured
syslog. PCC now distinguishes enforced retention from policy-only and
configuration-dependent retention.

The main accuracy constraints are:

- legal documents must not say all Home data is deleted on one timetable;
- the Family retention service enforces a 90-day Home-data lifecycle, but
  support screenshots, audit records, logs, billing and backups have separate
  conditions;
- Driveway/DVLA information can be unavailable or stale and is not keeper
  information in the current lookup contract;
- Budget is manual and has no bank connection;
- Graylog/syslog is an operator-configured destination, not a default
  monitoring processor;
- Apple, Google, Cloudflare, hosting, email, Stripe and DVLA require current
  provider/transfer/DPA details before the public policy is finalised.

## PCC operator guidance: privacy requests

1. Record the request type that best describes what the person is asking for.
2. Verify identity proportionately before disclosing or changing information;
   use the identity status field and record the operational evidence in
   internal notes. Do not upload unnecessary identity documents.
3. Record the statutory due date and monitor the overdue indicator. If the
   case is complex, likely to involve an exemption, or needs an extension,
   escalate to the privacy/legal owner rather than making an automated legal
   decision.
4. Assign ownership where that field is enabled, keep notes factual, and use
   `completed` or `declined` only after the operator has recorded the outcome
   and reason. A decline is not a substitute for legal review.
5. Do not place private request notes in consumer-visible fields. Preserve the
   audit trail and avoid secrets or unnecessary personal data.

## Launch readiness

Automated checks:

- [ ] Terms draft reviewed and intentionally published
- [ ] Privacy Policy draft reviewed and intentionally published
- [ ] Children's Privacy Notice draft reviewed and intentionally published
- [ ] Cookie Policy draft reviewed and intentionally published
- [ ] no unresolved placeholders remain in a document proposed for publication
- [ ] privacy contact configured and monitored
- [ ] support contact configured and monitored
- [ ] active/configuration-dependent subprocessors reviewed in PCC
- [ ] DPA and international-transfer details reviewed for each applicable provider
- [ ] retention findings reviewed against deployed jobs and backup policy
- [ ] adult signup/legal gate tested with the exact published versions
- [ ] guardian/child flow tested with the exact published child version

Manual/legal checks:

- [ ] External legal/privacy review completed
- [ ] lawful-basis and balancing review completed
- [ ] children’s-data/DPIA and UK Children’s Code review completed
- [ ] consumer subscription/cancellation review completed
- [ ] marketing/PECR review completed
- [ ] DVLA production terms and permitted-use review completed
- [ ] accessibility review completed
- [ ] incident, breach and privacy-request escalation contacts tested

The PCC launch view must not mark the manual/legal checks complete merely
because automated repository checks are green.

## UK operational preparation

- [ ] Confirm legal entity, company number, registered office and public
  website disclosures.
- [ ] Assess the ICO data-protection fee requirement.
- [ ] Maintain a Record of Processing Activities and lawful-basis review.
- [ ] Complete DPIA/children’s-data and Children’s Code assessments.
- [ ] Obtain processor agreements and assess international transfers.
- [ ] Test breach response, privacy-rights handling, retention and account/Home
  deletion procedures.
- [ ] Prepare Apple App Privacy and Google Play Data Safety submissions from
  the actual data inventory; do not guess or submit automatically.
- [ ] Review subscription consumer-law, marketing/PECR, DVLA, accessibility,
  and solicitor/privacy advice requirements.

## App Store / Google Play data mapping

Prepare the external forms from these repository categories, confirming each
provider and purpose at release time:

| Category | MyKhaya purpose | Review before submission |
| --- | --- | --- |
| Contact/account | Email, display name, authentication | Account operation, security, support |
| User content | Calendar, Nudges, Meals, lists, Budget, Driveway | Household coordination; sharing scope |
| Child information | Managed-child profile/login and guardian records | Children’s Code/DPIA and visibility |
| Diagnostics/security | Sessions, device/push registration, logs, audit | Required/optional distinction and retention |
| Purchases | Subscription/Stripe identifiers and billing state | Stripe disclosure; no full card storage |
| Vehicle data | Registration and returned vehicle fields | DVLA terms, UK lookup purpose, stale data |

Apple and Google classification, tracking declarations, retention, deletion and
whether a category is linked to identity require current platform forms and
human review.

## Publication and reconciliation controls

Phase 5 seeds only drafts with acceptance disabled. Do not publish by migration,
create acceptance history, or force a gate before an authorised PCC operator
has reviewed the exact content. After publication, verify draft → publish →
immutable version → consumer status → exact-version action → immutable audit
record → PCC history. Existing enabled child logins are not retrospectively
disabled or given manufactured guardian records; new enable/re-enable actions
use the currently published child document when configured as required.

## Open decisions before production

- Complete entity/contact placeholders.
- Confirm provider names, locations, DPAs and transfer mechanisms in PCC.
- Confirm deployed backup, audit, support attachment and log retention.
- Confirm cancellation/downgrade period-end behaviour against the live Stripe
  configuration.
- Obtain legal decisions on lawful bases, children’s data, exemptions,
  international transfers, consumer terms and governing law.
