"""Seed reviewed-before-publication Legal & Compliance draft documents.

The rows are deliberately drafts and have acceptance_required=false. This
migration provides editable starting content for PCC review; it never
publishes policy, changes a live gate, or creates acceptance history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0102_phase5_legal_drafts"
down_revision: str | None = "0101_compliance_phase4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENTS = sa.table(
    "legal_documents",
    sa.column("id", sa.UUID()),
    sa.column("key", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column(
        "audience",
        postgresql.ENUM("adult", "child", name="legal_audience", create_type=False),
    ),
    sa.column(
        "action_verb",
        postgresql.ENUM("accept", "acknowledge", name="legal_action_verb", create_type=False),
    ),
    sa.column("acceptance_required", sa.Boolean()),
)
_VERSIONS = sa.table(
    "legal_document_versions",
    sa.column("id", sa.UUID()),
    sa.column("document_id", sa.UUID()),
    sa.column("version_sequence", sa.Integer()),
    sa.column("version", sa.String()),
    sa.column(
        "status",
        postgresql.ENUM(
            "draft",
            "scheduled",
            "published",
            "superseded",
            name="legal_document_version_status",
            create_type=False,
        ),
    ),
    sa.column("content_markdown", sa.Text()),
    sa.column("change_summary", sa.String()),
    sa.column(
        "reacceptance_scope",
        postgresql.ENUM(
            "none",
            "new_users_only",
            "all_existing_users",
            name="legal_reacceptance_scope",
            create_type=False,
        ),
    ),
)

_TERMS_ID = "00000000-0000-0000-0000-000000000102"
_PRIVACY_ID = "00000000-0000-0000-0000-000000000103"
_CHILDREN_ID = "00000000-0000-0000-0000-000000000104"
_COOKIES_ID = "00000000-0000-0000-0000-000000000105"

_TERMS = """# MyKhaya Terms & Conditions

**Draft for review — not yet in force.** This draft contains placeholders and
must be reviewed by an authorised MyKhaya operator and appropriate legal
adviser before publication.

## 1. Who we are and these terms

MyKhaya is operated by **[LEGAL ENTITY NAME]**, company number
**[COMPANY NUMBER]**, registered office **[REGISTERED OFFICE]**. These terms
govern your use of the MyKhaya household coordination service. Contact us at
**[SUPPORT CONTACT EMAIL]**.

## 2. Accounts and security

You must provide accurate account details, be eligible to use the service in
your jurisdiction, and keep your password, passkeys, recovery codes and
devices secure. You are responsible for activity carried out through your
account and must tell us promptly about suspected compromise. We may require
email verification, MFA or a recent authentication step for sensitive actions.

## 3. Homes and managed children

A Home is a shared household space. Home Admins manage membership and may
invite or remove members. Members should only add information they have the
right to share. A managed-child account is created and controlled through its
Home and guardian relationships. Guardians remain responsible for deciding
whether a child should use MyKhaya and for supervising access. Child
acknowledgement and guardian authorisation are separate records.

## 4. Household features and content

MyKhaya may provide Calendar, Nudges, reminders, to-dos, Meals, household
lists, Wishlists, Budget and Driveway features depending on the Home's plan and
configuration. You retain responsibility for the content you enter. Private
household data is intended to remain private to the household unless you
deliberately share it with members, support, or an enabled integration.

Budget is a manual household-organising tool, not financial advice. It does
not connect to bank accounts. Driveway and DVLA-derived information may be
incomplete, delayed or unavailable. MyKhaya is not DVLA and does not replace
your responsibility for MOT, tax, insurance or other legal obligations.

## 5. Notifications and third-party services

We may send operational push or email notifications that you request or that
are needed to operate features, such as reminders and account-security
messages. These are not automatically marketing communications. Email,
push/APNS/FCM, Stripe, Apple, Google, DVLA services, hosting and any
operator-configured Graylog/syslog or Cloudflare deployment may process data
as described in the Privacy Policy and only where the relevant feature or
deployment is enabled.

## 6. Plans, billing and cancellation

The Free plan has the limits shown in the product. Family and Ultimate are
recurring paid plans where offered. The checkout screen states the selected
plan, amount and monthly or annual interval before payment. Stripe processes
payment details; MyKhaya does not store full card numbers. Subscriptions renew
until cancelled through the available MyKhaya/Stripe billing controls.

Cancellation normally stops the next renewal and access continues according to
the subscription state and period-end behaviour shown in the product. Plan
upgrades, downgrades and complimentary access are subject to the entitlement
and billing state recorded for the Home. We will not describe a deletion or
retention consequence at checkout that the backend does not enforce.

## 7. Availability, acceptable use and suspension

We aim to provide a reliable service but do not guarantee uninterrupted
availability or that external data is current. Do not misuse the service,
attempt unauthorised access, upload unlawful content, abuse other users, or
interfere with the service. We may suspend or close access for security,
legal, payment, abuse or operational reasons and will explain where practical.

## 8. Closure, intellectual property and liability

You may ask us about account closure, Home administration and deletion. Leaving
an individual Home does not necessarily delete shared Home content. Home
closure and account anonymisation follow the actual lifecycle and retention
processes described in the Privacy Policy; backups and security records may
remain for their operational or legal period.

MyKhaya and its licensors retain rights in the service, branding and software.
Subject to mandatory consumer rights, the service is provided with reasonable
care and skill, but we exclude guarantees that the service or third-party data
will be complete, current or uninterrupted. Nothing limits liability that the
law does not permit us to limit.

## 9. Changes, law and contact

We may update these terms by publishing a new version and explaining material
changes. Where the change requires renewed action, the product will ask for it
after an authorised publication. These terms are intended to be governed by
the law of **[GOVERNING LAW / JURISDICTION]**, subject to mandatory consumer
protections.

Questions: **[SUPPORT CONTACT EMAIL]**. Privacy questions: **[PRIVACY CONTACT EMAIL]**.
"""

_PRIVACY = """# MyKhaya Privacy Policy

**Draft for review — not yet in force.** This document describes the current
architecture as understood from the repository. The final entity, contacts,
provider contracts, transfer details and legal bases require human review.

## 1. Who controls your information

The controller is intended to be **[LEGAL ENTITY NAME]**, company number
**[COMPANY NUMBER]**, registered office **[REGISTERED OFFICE]**. Contact
**[PRIVACY CONTACT EMAIL]**. MyKhaya does not sell private household data or
children's data and does not use children's information for behavioural
advertising.

## 2. Information we use

We may process account identity, display name, email address, verification and
authentication information, MFA/passkey and recovery-code state, sessions,
device and security metadata. We process Home membership, roles,
relationships, invitations and household content such as calendar events,
tags, shared calendars, Nudges, routines, reminders, to-dos, Meals, lists,
Wishlists and notifications.

Budget entries are manually entered amounts, categories, notes and sharing
settings. MyKhaya has no bank connection in this implementation and does not
receive bank-account transaction feeds. Driveway may contain registration,
vehicle make/model, photos, notes, optional VIN and reminders. A UK DVLA
lookup may return vehicle information for the lookup purpose; the current
integration does not claim to retrieve keeper identity.

Support may include messages, screenshots and optional diagnostics. Technical
records include push-registration tokens, email delivery metadata, jobs,
audit/security records, application logs, request identifiers and operational
delivery metrics. Payment and subscription records include plan, interval,
Stripe identifiers and billing state. Stripe receives payment details; MyKhaya
does not store full card numbers.

## 3. Why we use it and possible legal bases

We use information to provide the service and Home features, authenticate
users, protect accounts, send requested operational notifications, support
users, process subscriptions, respond to legal requests, and maintain service
security. The likely basis is performance of the contract for core account and
household services; legitimate interests for security, service reliability,
support and operational audit; legal obligation where records are required;
and consent only where a genuinely optional consent choice is presented.
The final basis and balancing assessments require legal review and are not
determined by this draft alone.

## 4. Household privacy and sharing

Private household data stays private to the household unless you deliberately
choose to share it through membership, a feature, support material or an
enabled integration. Home Admins and members may see information according to
the relevant Home role and sharing setting. Budget has individual and partner
sharing levels; a combined view does not make MyKhaya a financial adviser.
Guardians and appropriate Home adults may see managed-child information needed
for household coordination. Children receive a clearer notice and their own
acknowledgement is distinct from guardian authorisation.

## 5. Providers and international processing

Depending on features and deployment, recipients may include hosting and
backup infrastructure, Stripe for billing, Apple and Google for native platform
services, a DVLA service for UK vehicle lookup, a configured email provider,
and operator-configured Graylog/syslog. Cloudflare may be present in some
deployments. The exact provider, location, DPA and transfer mechanism must be
recorded in PCC before launch; this draft does not claim all data stays in the
UK or invent a transfer mechanism. MyKhaya's own local logs are not evidence
of a separate monitoring SaaS processor.

## 6. Retention and deletion

Active account information is kept while needed to operate the account. Home
data follows the implemented Home lifecycle; the current repository enforces
a 90-day Family retention process for Home-owned data after authoritative
expiry, while some personal calendar data is preserved by that service.
Support screenshots, audit records, local/application logs, syslog/Graylog,
billing records and backups have separate operational, deployment or legal
retention conditions. PCC distinguishes enforced rules from policy-only and
configuration-dependent items. We do not claim that every category is deleted
after one common period.

Account closure, leaving a Home, Home closure and anonymisation are different
operations. Removing one account does not automatically remove shared Home
content. Backups and security/audit records may persist for their applicable
period. Submit a privacy request for questions about access, correction,
erasure, restriction, objection or portability.

## 7. Rights and children

Depending on your circumstances and applicable law, you may have rights to
access, correct, delete, restrict or object to processing, and request a copy
of information. We may verify identity before acting and may need to preserve
some information. Guardians should contact us about a child's information;
children can ask a trusted adult for help. Requests should be sent to
**[PRIVACY CONTACT EMAIL]**.

## 8. Cookies, notifications and marketing

The browser uses first-party session/security technology and functional local
storage where needed for the application. The current repository audit found
no advertising tracking, behavioural advertising or third-party analytics.
Operational push and email messages are service communications, not
automatically marketing. If non-essential tracking is introduced, the consent
approach will be reviewed before deployment.

## 9. Changes and contact

We may publish a new version through PCC. The exact version and action taken
are recorded for acceptance, acknowledgement and guardian/child actions.
Contact **[PRIVACY CONTACT EMAIL]** or **[SUPPORT CONTACT EMAIL]**.
"""

_CHILDREN = """# Family & Children's Privacy Notice

**Draft for review — not yet in force.**

## What is MyKhaya?

MyKhaya is a private household organiser. Families can use it for calendars,
reminders, meals, lists, vehicles and other Home activities.

## What information may be kept?

Your Home may keep your name, avatar, login and security information, and
information adults add for household coordination. This can include events,
reminders, tasks, meals, lists and information about a vehicle. The service
only needs this information to provide the Home features that your family
uses.

## Who can see it?

People in your Home may see information according to the Home's sharing and
role settings. Adults responsible for your Home may be able to manage your
account and see information needed to keep the Home working. MyKhaya does not
sell your information and does not use it for behavioural advertising.

## Why does MyKhaya need it?

It helps your family organise everyday life, keep accounts safe, send requested
reminders and provide support. MyKhaya may need to send limited information to
services that help it work, such as hosting, email, push notifications, a
vehicle lookup or billing when those features are used. The adult Privacy
Policy explains this in more detail.

## Your choices and questions

Ask a parent or guardian for help before using your account. You can ask what
information is held about you or ask an adult to contact **[PRIVACY CONTACT EMAIL]**.
For product help, contact **[SUPPORT CONTACT EMAIL]**. We will not treat this
notice as the same thing as your guardian's authorisation: a guardian action
and your acknowledgement are recorded separately.
"""

_COOKIES = """# MyKhaya Cookie Policy

**Draft for review — not yet in force.**

MyKhaya currently uses first-party session and security technology so that the
browser can keep you signed in safely, protect requests and support account
authentication. It may also use functional browser storage for application
preferences or state needed by the service.

The current implementation does not identify advertising cookies, behavioural
advertising or third-party analytics. We do not use those technologies to
profile household members or children.

You can control cookies and site storage through your browser settings, but
blocking session or security storage may prevent sign-in or core features from
working. If MyKhaya introduces non-essential tracking technologies in future,
the consent approach will be reviewed before deployment.

Questions: **[PRIVACY CONTACT EMAIL]**.
"""


def upgrade() -> None:
    bind = op.get_bind()
    documents = [
        {
            "id": _TERMS_ID,
            "key": "terms",
            "display_name": "Terms & Conditions",
            "audience": "adult",
            "action_verb": "accept",
            "acceptance_required": False,
        },
        {
            "id": _PRIVACY_ID,
            "key": "privacy",
            "display_name": "Privacy Policy",
            "audience": "adult",
            "action_verb": "acknowledge",
            "acceptance_required": False,
        },
        {
            "id": _CHILDREN_ID,
            "key": "children_privacy",
            "display_name": "Family & Children's Privacy Notice",
            "audience": "child",
            "action_verb": "acknowledge",
            "acceptance_required": False,
        },
        {
            "id": _COOKIES_ID,
            "key": "cookies",
            "display_name": "Cookie Policy",
            "audience": "adult",
            "action_verb": "acknowledge",
            "acceptance_required": False,
        },
    ]
    bind.execute(sa.insert(_DOCUMENTS), documents)
    bind.execute(
        sa.insert(_VERSIONS),
        [
            {
                "id": f"00000000-0000-0000-0000-00000000020{i}",
                "document_id": row["id"],
                "version_sequence": 1,
                "version": "1.0",
                "status": "draft",
                "content_markdown": content,
                "change_summary": "Initial Phase 5 draft for human review.",
                "reacceptance_scope": "new_users_only",
            }
            for i, (row, content) in enumerate(
                zip(documents, (_TERMS, _PRIVACY, _CHILDREN, _COOKIES), strict=True), start=2
            )
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.delete(_VERSIONS).where(
            _VERSIONS.c.document_id.in_([_TERMS_ID, _PRIVACY_ID, _CHILDREN_ID, _COOKIES_ID])
        )
    )
    bind.execute(
        sa.delete(_DOCUMENTS).where(
            _DOCUMENTS.c.id.in_([_TERMS_ID, _PRIVACY_ID, _CHILDREN_ID, _COOKIES_ID])
        )
    )
