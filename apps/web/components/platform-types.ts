// Shared types for the new MFA/administrator-security surface. Most existing
// Control Centre pages redeclare their own local response shapes inline
// (there's no shared platform-types module in this codebase yet) — this file
// exists because the MFA flow's shapes are reused across several new pages
// (login, setup-mfa, security, administrators), not to retrofit the rest of
// the Control Centre.

export type PlatformSessionStatus = "full" | "pending_mfa" | "mfa_setup_required";

export type PlatformActor = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  mfa_enrolled: boolean;
  session_status: PlatformSessionStatus;
  // Only populated at session_status "pending_mfa" — the fallback methods
  // that genuinely exist for this account, so the login page never offers a
  // method that isn't actually set up. Optional here only because existing
  // callers construct PlatformActor values for other session statuses,
  // where the backend always sends an empty array.
  available_factors?: ("passkey" | "totp" | "recovery_code")[];
  // Only populated once, atomically with the response that completes this
  // administrator's first MFA factor — never retrievable again afterwards.
  recovery_codes?: string[] | null;
};

export type WebAuthnCredential = {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
};

// PCC-SEC-006: GET /administrators/{id}/security returns one of two shapes
// depending on the viewer's role — the full detail (with per-credential and
// per-session data) for an Owner viewer, or a reduced summary (counts only,
// no raw session IPs/user-agents/session IDs, no per-credential labels) for
// an Administrator/Security viewer. Modelled as one type with the
// full-detail-only fields optional, rather than two separate types, so the
// tab components below can render either shape without a big branch.
export type AdministratorSecurity = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  mfa_enrolled: boolean;
  totp_enabled: boolean;
  totp_verified_at: string | null;
  recovery_codes_remaining: number;
  // Full-detail fields — present only when the viewer is an Owner.
  webauthn_credentials?: WebAuthnCredential[];
  sessions?: AdminSessionSummary[];
  // Summary fields — present only when the viewer is an Administrator or
  // Security operator (i.e. webauthn_credentials/sessions are absent).
  webauthn_credential_count?: number;
  active_session_count?: number;
  last_seen_at?: string | null;
};

export type AdminSessionSummary = {
  id: string;
  created_at: string;
  last_seen_at: string;
  absolute_expires_at: string;
  user_agent: string;
  source_ip: string;
  // Only present when viewing your own session list.
  current?: boolean;
};

export type MfaPolicy = {
  required: boolean;
  environment_enforced: boolean;
};

export type InvitationState = "pending" | "accepted" | "expired" | "revoked";

export type AdministratorInvitation = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  state: InvitationState;
  invited_by_display_name: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
};

export type AdministratorInvitationPreview = {
  email: string;
  display_name: string;
  role: string;
  invited_by_display_name: string | null;
  expires_at: string;
};

// Phase 2 commercial entitlements (Platform Control Centre "Subscriptions"
// area). Mirrors mykhaya.platform_schemas' HomeSubscriptionResponse /
// SubscriptionSummaryResponse / SubscriptionListItem / SubscriptionDetailResponse
// — see docs/architecture/commercial-entitlements.md.

export type HomeSubscription = {
  plan: string;
  provider: string;
  status: string;
  billing_owner_user_id: string | null;
  external_customer_id: string | null;
  external_subscription_id: string | null;
  external_price_id: string | null;
  billing_interval: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  complimentary_reason: string | null;
  complimentary_note: string | null;
  complimentary_granted_by: string | null;
  complimentary_granted_by_display_name: string | null;
  complimentary_granted_at: string | null;
  complimentary_expires_at: string | null;
  effective_plan: string;
  effective_status_reason: string | null;
};

export type SubscriptionSummary = {
  total_homes: number;
  free: number;
  family: number;
  complimentary: number;
  complimentary_expired: number;
  past_due: number;
  cancelled: number;
  stripe_total: number;
  stripe_active_family: number;
  stripe_monthly: number;
  stripe_annual: number;
  stripe_cancelling: number;
};

export type SubscriptionListItem = {
  id: string;
  name: string;
  stored_plan: string;
  provider: string;
  status: string;
  effective_plan: string;
  effective_status_reason: string | null;
  complimentary_expires_at: string | null;
  member_count: number;
  last_commercial_change: string | null;
};

export type SubscriptionListResponse = {
  items: SubscriptionListItem[];
  page: number;
  page_size: number;
  total: number;
};

export type Entitlements = {
  plan: string;
  booleans: Record<string, boolean>;
  limits: Record<string, number | null>;
};

export type SubscriptionEvent = {
  id: string;
  created_at: string;
  event_type: string;
  from_plan: string | null;
  to_plan: string | null;
  from_provider: string | null;
  to_provider: string | null;
  from_status: string | null;
  to_status: string | null;
  actor_administrator_id: string | null;
  actor_display_name: string | null;
  reason: string | null;
};

export type HomeAdministratorSummary = {
  user_id: string;
  display_name: string;
  email: string;
};

export type StripePriceInfo = {
  currency: string;
  unit_amount: number;
  formatted_amount: string;
};

export type CalendarUsage = {
  count: number;
  limit: number | null;
  over_limit: boolean;
};

export type WebhookEventSummary = {
  id: string;
  stripe_event_id: string;
  event_type: string;
  received_at: string;
  outcome: string;
};

export type WebhookFailureSummary = {
  id: string;
  stripe_event_id: string | null;
  event_type: string | null;
  error_message: string;
  occurred_at: string;
};

export type StripeWebhookHealth = {
  configured: boolean;
  state: string;
  reason: string | null;
  last_event_at: string | null;
  recent_failure_count: number;
  recent_events: WebhookEventSummary[];
  recent_failures: WebhookFailureSummary[];
  mode: string;
  source: string;
  paid_homes: number;
};

// Platform Control Centre "Payments" area — mirrors
// mykhaya.platform_schemas' StripeConfigurationResponse /
// StripeModeSettingsResponse / StripeTestConnectionResponse. See
// docs/architecture/platform-control-centre.md#stripe-configuration-precedence.

export type StripeModeSettings = {
  publishable_key: string | null;
  secret_key_configured: boolean;
  secret_key_last4: string | null;
  webhook_secret_configured: boolean;
  webhook_secret_last4: string | null;
  family_monthly_price_id: string | null;
  family_annual_price_id: string | null;
};

export type StripeWebhookSummary = {
  configured: boolean;
  state: string;
  reason: string | null;
  last_event_at: string | null;
  recent_failure_count: number;
  endpoint_url: string | null;
};

export type StripeConfiguration = {
  configured: boolean;
  enabled: boolean;
  mode: "test" | "live";
  source: "database" | "environment" | "unconfigured";
  incomplete_reason: string | null;
  editable: boolean;
  updated_at: string | null;
  test: StripeModeSettings;
  live: StripeModeSettings;
  webhook: StripeWebhookSummary;
};

export type StripeTestConnectionResult =
  | "connected"
  | "authentication_failed"
  | "stripe_unavailable"
  | "configuration_incomplete"
  | "network_failure";

export type StripeTestConnectionResponse = {
  result: StripeTestConnectionResult;
  detail: string;
  mode: "test" | "live";
};

export type SubscriptionDetail = {
  id: string;
  name: string;
  created_at: string;
  member_count: number;
  administrators: HomeAdministratorSummary[];
  subscription: HomeSubscription;
  entitlements: Entitlements;
  calendar_usage: CalendarUsage;
  member_usage: CalendarUsage;
  personal_routines_total: number;
  recent_webhook_events: WebhookEventSummary[];
  history: SubscriptionEvent[];
  stripe_price: StripePriceInfo | null;
  stripe_dashboard_customer_url: string | null;
  stripe_dashboard_subscription_url: string | null;
};

export const PLATFORM_ROLES: { value: string; label: string }[] = [
  { value: "platform_owner", label: "Owner" },
  { value: "platform_administrator", label: "Administrator" },
  { value: "security_operator", label: "Security" },
  { value: "support_operator", label: "Support" },
  { value: "read_only_operator", label: "Read-only" },
];
