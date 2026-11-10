"""Every monitored component, what it verifies, and which public service(s)
its state feeds.

The code catalogue supplies defaults; the matching ``monitor_components``
row holds the live configuration (editable in PCC) and current state. To add
a dependency, add a check in ``checks`` and a ``ComponentDefinition`` here:
see docs/operations/service-monitoring.md "Adding a new external dependency".

Public service keys are the ones in mykhaya.status_aggregation
(PUBLIC_SERVICES for MyKhaya's own services, EXTERNAL_SERVICES for the
External Services section). A component can feed several services: the
database being down affects the API, Authentication and Background
Processing alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from mykhaya.monitoring import checks
from mykhaya.monitoring.checks import CheckFn

RUNNER_COMPONENT_KEY = "monitoring.runner"


@dataclass(frozen=True)
class ComponentDefinition:
    key: str
    name: str
    service_keys: tuple[str, ...]
    check_type: str
    # What a success actually proves, shown in PCC so nobody mistakes a
    # reachability probe for end-to-end verification.
    verifies: str
    # Used in administrator alert emails.
    customer_impact: str
    run: CheckFn
    category: str = "internal"  # internal | external
    provider: str | None = None
    interval_seconds: int = 60
    timeout_seconds: int = 10
    failure_threshold: int = 3
    recovery_threshold: int = 3
    severity: str = "critical"  # critical | warning | info
    public_visible: bool = True
    # Observed by the worker watchdog rather than the scheduler's runner.
    watchdog_managed: bool = False
    # The result depends on the network path from MyKhaya's own server
    # (public hostnames behind Cloudflare, third-party endpoints). Such checks
    # start as PCC-only: they record, display and alert, but cannot change the
    # public page or open an incident until an administrator has validated
    # them from the live environment and enabled public reporting (audited).
    requires_live_validation: bool = False


CATALOGUE: tuple[ComponentDefinition, ...] = (
    # --- MyKhaya Web Application ---
    ComponentDefinition(
        key="web.http",
        name="Web application (internal)",
        service_keys=("web_application",),
        check_type="http",
        verifies="The web container serves its home page over the internal Docker network "
        "(as Caddy forwards it). Internal health only: not internet reachability.",
        customer_impact="The MyKhaya web app may not load.",
        run=checks.check_web_http,
    ),
    # --- API ---
    ComponentDefinition(
        key="api.database",
        name="Database",
        service_keys=("api", "authentication", "background_processing"),
        check_type="database",
        verifies="PostgreSQL answers a query.",
        customer_impact="Most of MyKhaya is unavailable; sign-in and saving changes will fail.",
        run=checks.check_database,
    ),
    ComponentDefinition(
        key="api.redis",
        name="Cache and queue (Redis)",
        service_keys=("api", "authentication", "background_processing"),
        check_type="redis",
        verifies="Redis answers PING.",
        customer_impact="Sign-in, rate limiting and background jobs may fail.",
        run=checks.check_redis,
    ),
    ComponentDefinition(
        key="api.ready",
        name="API readiness",
        service_keys=("api",),
        check_type="http",
        verifies="The API container's readiness endpoint over the internal Docker network "
        "(database, Redis and schema version checked by the API itself).",
        customer_impact="The apps cannot load or save data.",
        run=checks.check_api_ready,
    ),
    ComponentDefinition(
        key="api.error_rate",
        name="API error rate and latency",
        service_keys=("api",),
        check_type="metrics",
        verifies="Share of real customer API requests failing with a server error, "
        "and their average latency, over the last 5 minutes.",
        customer_impact="Some actions in the apps may fail or be slow.",
        run=checks.check_api_error_rate,
        severity="warning",
    ),
    # --- Authentication ---
    ComponentDefinition(
        key="auth.endpoint",
        name="Authentication service",
        service_keys=("authentication",),
        check_type="http",
        verifies="The authentication router answers a read-only status request over the "
        "internal Docker network. No sign-in is attempted and no account is created.",
        customer_impact="Customers may be unable to sign in or register.",
        run=checks.check_auth_endpoint,
    ),
    ComponentDefinition(
        key="auth.error_rate",
        name="Authentication error rate",
        service_keys=("authentication",),
        check_type="metrics",
        verifies="Share of real sign-in/registration requests failing with a server error.",
        customer_impact="Some customers may be unable to sign in.",
        run=checks.check_auth_error_rate,
        severity="warning",
    ),
    # --- Email Delivery ---
    ComponentDefinition(
        key="email.smtp",
        name="Mail server connection",
        service_keys=("email_delivery",),
        check_type="smtp",
        verifies="Connects, negotiates TLS and authenticates to the configured mail server. "
        "No message is sent.",
        customer_impact="Emails (verification, invitations, reminders) may not be sent.",
        run=checks.check_smtp,
        interval_seconds=300,
        recovery_threshold=2,
    ),
    ComponentDefinition(
        key="email.delivery",
        name="Email delivery outcomes",
        service_keys=("email_delivery",),
        check_type="passive",
        verifies="Real email delivery attempts in the last 30 minutes, "
        "and emails stuck in the queue.",
        customer_impact="Emails may be delayed or not delivered.",
        run=checks.check_email_delivery,
    ),
    # --- Notifications ---
    ComponentDefinition(
        key="notifications.push_delivery",
        name="Push delivery outcomes",
        service_keys=("notifications",),
        check_type="passive",
        verifies="Real production push deliveries (Web Push, Android, production iOS) "
        "in the last hour. No test pushes are sent.",
        customer_impact="Push notifications may not arrive.",
        run=checks.check_push_delivery,
    ),
    ComponentDefinition(
        key="notifications.apns",
        name="Apple Push Notification service reachability",
        service_keys=("notifications",),
        check_type="tls",
        verifies="DNS and TLS to Apple's production push gateway. No push is sent.",
        customer_impact="iPhone push notifications may not arrive.",
        run=checks.check_apns_reachability,
        category="external",
        provider="Apple",
        interval_seconds=300,
        severity="warning",
        requires_live_validation=True,
    ),
    ComponentDefinition(
        key="notifications.fcm",
        name="Firebase Cloud Messaging reachability",
        service_keys=("notifications",),
        check_type="tls",
        verifies="DNS and TLS to Google's push gateway. No push is sent.",
        customer_impact="Android push notifications may not arrive.",
        run=checks.check_fcm_reachability,
        category="external",
        provider="Google",
        interval_seconds=300,
        severity="warning",
        requires_live_validation=True,
    ),
    # --- Background Processing ---
    ComponentDefinition(
        key="background.worker",
        name="Worker heartbeat",
        service_keys=("background_processing",),
        check_type="heartbeat",
        verifies="The background worker recorded a heartbeat recently.",
        customer_impact="Reminders, emails and notifications will not be processed.",
        run=checks.check_worker_heartbeat,
        failure_threshold=2,
    ),
    ComponentDefinition(
        key="background.outbox",
        name="Job queue progress",
        service_keys=("background_processing",),
        check_type="queue",
        verifies="Due background work is being completed.",
        customer_impact="Reminders, emails and notifications may be delayed.",
        run=checks.check_outbox_progress,
    ),
    ComponentDefinition(
        key="background.failed_jobs",
        name="Failing jobs",
        service_keys=("background_processing",),
        check_type="queue",
        verifies="How many background jobs are currently failing and being retried.",
        customer_impact="Some reminders, emails or notifications may be delayed.",
        run=checks.check_failed_jobs,
        severity="warning",
    ),
    # --- Billing & Subscriptions / Stripe ---
    ComponentDefinition(
        key="billing.stripe_api",
        name="Stripe API",
        service_keys=("stripe_payments", "billing"),
        check_type="api_read",
        verifies="An authenticated, read-only Stripe API request with this environment's key. "
        "No payment or customer is created.",
        customer_impact="Customers may be unable to subscribe or manage their subscription.",
        run=checks.check_stripe_api,
        category="external",
        provider="Stripe",
        interval_seconds=300,
        recovery_threshold=2,
        requires_live_validation=True,
    ),
    ComponentDefinition(
        key="billing.stripe_webhooks",
        name="Stripe webhook processing",
        service_keys=("stripe_webhooks", "billing"),
        check_type="passive",
        verifies="Failures processing real Stripe webhooks in the last hour. "
        "Cannot detect Stripe silently not sending events.",
        customer_impact="Subscription changes may take longer to apply.",
        run=checks.check_stripe_webhooks,
        category="external",
        provider="Stripe",
        severity="warning",
    ),
    # --- External providers ---
    ComponentDefinition(
        key="provider.dvsa.connectivity",
        name="DVSA MOT History connectivity",
        service_keys=("dvsa_mot_history",),
        check_type="tls",
        verifies="DNS and TLS to the DVSA API and its token service. No MOT lookup is made.",
        customer_impact="Vehicle MOT history retrieval may be unavailable.",
        run=checks.check_dvsa_connectivity,
        category="external",
        provider="DVSA",
        interval_seconds=300,
        recovery_threshold=2,
        requires_live_validation=True,
    ),
    ComponentDefinition(
        key="provider.dvsa.observed",
        name="DVSA MOT History lookups",
        service_keys=("dvsa_mot_history",),
        check_type="passive",
        verifies="Outcomes of real customer MOT lookups. No synthetic lookups are made.",
        customer_impact="Vehicle MOT history retrieval may be failing.",
        run=checks.check_dvsa_observed,
        category="external",
        provider="DVSA",
    ),
    ComponentDefinition(
        key="provider.dvla.connectivity",
        name="DVLA Vehicle Enquiry connectivity",
        service_keys=("dvla_vehicle_enquiry",),
        check_type="tls",
        verifies="DNS and TLS to the DVLA Vehicle Enquiry API. No vehicle lookup is made.",
        customer_impact="Adding a vehicle by registration may be unavailable.",
        run=checks.check_dvla_connectivity,
        category="external",
        provider="DVLA",
        interval_seconds=300,
        recovery_threshold=2,
        requires_live_validation=True,
    ),
    ComponentDefinition(
        key="provider.apple.sign_in",
        name="Apple Sign-In",
        service_keys=("apple_sign_in",),
        check_type="jwks",
        verifies="Apple's public sign-in keys can be fetched. No sign-in is attempted.",
        customer_impact="Sign in with Apple may be unavailable.",
        run=checks.check_apple_sign_in,
        category="external",
        provider="Apple",
        interval_seconds=300,
        recovery_threshold=2,
        requires_live_validation=True,
    ),
    ComponentDefinition(
        key="provider.google.sign_in",
        name="Google Sign-In",
        service_keys=("google_sign_in",),
        check_type="jwks",
        verifies="Google's public sign-in keys can be fetched. No sign-in is attempted.",
        customer_impact="Sign in with Google may be unavailable.",
        run=checks.check_google_sign_in,
        category="external",
        provider="Google",
        interval_seconds=300,
        recovery_threshold=2,
        requires_live_validation=True,
    ),
    # --- Monitoring itself ---
    ComponentDefinition(
        key=RUNNER_COMPONENT_KEY,
        name="Monitoring runner",
        service_keys=(),
        check_type="watchdog",
        verifies="The scheduler's monitoring cycle has completed recently "
        "(observed independently by the worker).",
        customer_impact="Service status cannot be verified; the public page shows Unknown.",
        run=checks.check_watchdog_managed,
        # Two missed minutes beyond the 3-minute staleness window: avoids a
        # false alarm when the worker starts moments before the scheduler.
        failure_threshold=2,
        recovery_threshold=1,
        public_visible=False,
        watchdog_managed=True,
    ),
)

BY_KEY: dict[str, ComponentDefinition] = {item.key: item for item in CATALOGUE}


def definition(key: str) -> ComponentDefinition | None:
    return BY_KEY.get(key)
