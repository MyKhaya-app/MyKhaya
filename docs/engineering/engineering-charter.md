# MyKhaya Engineering Charter

- **Version:** 1.2
- **Status:** Approved in principle; adoption pending Owner commit approval
- **Applies to:** All developers, AI coding agents and contributors, for all work
- **Authority:** MyKhaya Project Owner

## Our mission

MyKhaya is a commercially owned family-management platform. Its source repository is
currently publicly accessible.

Public access to the source code does not grant an open-source licence. Licensing and
distribution permissions are determined solely by the Owner.

Our purpose is to build a secure, reliable, intuitive and maintainable application that
families can trust.

MyKhaya is an established product. We build on its existing architecture rather than
repeatedly reinventing it.

This charter sets the principles. The linked standards hold the detailed technical
requirements and remain authoritative in their areas.

## The ten non-negotiable principles

### 1. Security before functionality

Security, privacy and data integrity take precedence over convenience, development speed
and feature requests.

Never weaken an existing trust boundary, expose an internal service, open a network port,
bypass TLS verification or reduce authentication protections simply to make
functionality work.

**New network exposure or changes to security boundaries require a documented security
assessment and explicit Owner approval.**

Authority: [Security Baseline](../security/security-baseline.md),
[Secure Development Lifecycle](../security/secure-development-lifecycle.md)

### 2. Understand before changing

Inspect the current repository, relevant implementations, engineering documentation and
established architectural decisions before designing or modifying functionality.

Never treat MyKhaya as a new application. Never propose a replacement without first
understanding the existing system.

Distinguish verified facts from assumptions. If repository inspection is unavailable,
say so.

Authority: [Engineering Standards](engineering-standards.md) and the architecture
decision records in `docs/architecture/adr/`

### 3. Reuse, simplify and preserve

Extend existing services and shared components wherever practical. Avoid unnecessary
dependencies, infrastructure, duplicated logic and speculative abstractions.

- All user-facing communications (email, push and in-app) originate from `notify()` in
  `apps/api/mykhaya/notifications/engine.py`. Modules never send email, push or in-app
  notifications directly.
- All commercial (plan-based) restrictions go through `mykhaya.entitlements`. Never write
  plan or provider comparisons in routers or domain modules.
- Unfinished functionality is controlled by the central server-side feature evaluator,
  `mykhaya.features.is_feature_enabled`. Hiding a navigation link is not feature
  enforcement.

Preserve existing working behaviour unless an approved change requires otherwise.

Authority: [Engineering Standards](engineering-standards.md),
[Notification Engine](../architecture/notification-engine.md),
[Commercial Entitlements](../architecture/commercial-entitlements.md),
[Feature Flags](../architecture/feature-flags.md)

### 4. Protect every Home and every identity

Families see their tenant as a Home, or Khaya. Internally, the tenant boundary is a
`group`, and isolation follows the established group-based architecture.

All data access enforces current membership, appropriate permissions and tenant isolation
server-side, using Home-scoped (group-scoped) access rather than unconstrained object
lookup.

Protect children, family information, account recovery and linked authentication
identities. Preserve MFA, native security controls and the Platform Control Centre's
(PCC's) separate administrative identity and authorisation boundaries.

Cross-Home access must be explicitly tested.

Authority: [Multi-Tenancy](../architecture/multi-tenancy.md),
[Security Baseline](../security/security-baseline.md)

### 5. Preserve DEV and PROD isolation

Development and production remain independent across databases, credentials,
authentication providers, billing, mobile identifiers, push notifications, configuration
and deployment.

Use `dev` for development. Only the Owner authorises promotion to `main`, production tags
and production releases.

Promotion to `main` must be enforced by GitHub branch protection or rulesets that require
a pull request and the mandatory `application` and `security-gate` checks, with no
force-push or deletion. Verify these controls in GitHub itself before relying on them.
Never claim a control is enforced merely because it is documented.

Never treat local agent tests as proof that the live DEV environment works.

Authority: [Git Branching Strategy](git-branching-strategy.md),
[Release Process](../operations/release-process.md),
[CI Security Scanning](ci-security-scanning.md)

### 6. Design for reliability and honest monitoring

Systems must fail safely, recover predictably and report their state accurately.

Monitor internal services through existing trusted application infrastructure wherever
practical. Distinguish internal health, provider connectivity and external customer
availability.

Never report an unverified or stale health observation as confirmed Operational.

Monitoring must not create security exposure, excessive provider traffic or avoidable
operational complexity.

Authority: [Engineering Standards](engineering-standards.md),
[Service Monitoring architecture](../architecture/service-monitoring.md),
[Service Monitoring operations](../operations/service-monitoring.md)

### 7. Respect the existing user experience

Maintain MyKhaya's established visual identity, navigation, components, forms and
responsive behaviour.

**The current native/mobile UI is the protected baseline.** This covers mobile browser
behaviour, the web/PWA presentation and the native iOS and Android shells. Desktop and
tablet work must not alter mobile geometry, safe areas, fixed navigation, sheets, viewport
scaling or touch behaviour. Mobile work must not constrain desktop or tablet to a
phone-width layout.

Validate user-facing changes on appropriate real devices, including a physical phone where
the standards require it.

Authority: [AGENTS.md](../../AGENTS.md),
[UI Platform Standards](ui-platform-standards.md),
[Mobile Standards](mobile-standards.md),
[Definition of Done](definition-of-done.md)

### 8. Prove quality; do not assume it

Test security boundaries, expected behaviour, failure paths and regressions in proportion
to the risk.

Passing mocked tests does not prove that live integrations or deployments work.

Maintain trustworthy CI, security scanning, dependency checks, migration validation and
release gates.

**A failed security check is investigated immediately, on any branch.** A failing
mandatory security check blocks release approval. It must not be ignored, left red or
routinely bypassed, and a finding is suppressed only through the documented triage
procedure.

Report failures and incomplete verification accurately.

Authority: [Definition of Done](definition-of-done.md),
[CI Security Scanning](ci-security-scanning.md),
[Secure Development Lifecycle](../security/secure-development-lifecycle.md)

### 9. Protect the repository and its knowledge

The repository is public. Never commit:

- secrets or credentials, including example values that are real;
- customer or personal data, including real backups, exports or screenshots of real data;
- unremediated vulnerability details that would materially assist exploitation;
- sensitive operational information, including private network topology, network
  access-control layouts, internal security configuration and machine-specific paths.

Ordinary architecture and engineering documentation that is safe and useful to publish
stays in the repository.

A credential committed to Git history is compromised and must be rotated. Removing it from
the current files is not enough.

Protect source-control history, preserve concurrent work and stage only intended changes.

Keep a single source of truth for engineering rules. Update affected architecture,
operational and engineering documentation alongside implementation. Do not introduce
contradictory or duplicate specifications, and do not commit generated output or local
tool settings.

Authority: [Engineering Standards](engineering-standards.md),
[Git Branching Strategy](git-branching-strategy.md),
[SECURITY.md](../../SECURITY.md)

### 10. The Owner retains final authority

AI agents and contributors may investigate, recommend and implement within their
authorised scope. They may not unilaterally change project direction, security
boundaries, licensing, repository visibility, release policy or production
infrastructure.

Significant changes require a clear explanation of impact, security implications,
testing, configuration, migrations and remaining risks.

Unsafe proposals must be challenged. Mistakes must be acknowledged and corrected at their
source.

**No implementation convenience overrides MyKhaya's security, privacy or Owner-approved
architecture.**

Authority: this charter and the repository's engineering and security standards.

## Conflicting instructions

If the charter, an engineering standard or the implementation conflicts with another
authoritative project requirement, stop, identify the conflict, report it and correct
the relevant documentation and implementation through the approved workflow. Never
silently choose whichever instruction is more convenient.

## Mandatory working agreement

Before every feature, fix, documentation change or architectural decision:

1. Read this charter and the relevant authoritative standards.
2. Inspect the current implementation and working-tree state.
3. Identify existing functionality to reuse and dependencies that may be affected.
4. Assess security, privacy, tenant isolation, deployment and regression risks.
5. Agree the smallest appropriate implementation within the authorised scope.
6. Verify changes through appropriate tests, and through live acceptance where required.
7. Update documentation and report results honestly.
8. Preserve unrelated work and follow the approved Git and release process.

When a requirement conflicts with a security control or architectural principle, stop and
explain the conflict before proceeding.

## Our engineering pledge

**Understand before changing.**

**Secure before exposing.**

**Reuse before rebuilding.**

**Simplify before complicating.**

**Protect every Home and every identity.**

**Verify before claiming success.**

**Document what actually exists.**

**Respect every environment and trust boundary.**

**Never release without authorisation.**

**Never compromise the trust that families place in MyKhaya.**
