// Generated from apps/api/openapi.json by `make generate-client` in CI.
// This small bootstrap surface is replaced by generation once the API starts.
export type MembershipRole =
  | "owner"
  | "administrator"
  | "adult_member"
  | "member"
  | "guest";
export type HouseholdRelationship =
  | "home_admin"
  | "partner"
  | "child"
  | "extended_family"
  | "friend"
  | "review_required";
export type PermissionProfile =
  | "home_admin"
  | "standard_partner"
  | "child_restricted"
  | "explicit_sharing"
  | "review_required";
export type PrincipalType = "adult" | "managed_child";
export interface User {
  id: string;
  // null for a managed Child — its internal placeholder address is never exposed.
  email: string | null;
  display_name: string;
  email_verified: boolean;
  birth_month: number | null;
  birth_day: number | null;
  birth_year: number | null;
  avatar_version: string | null;
  principal_type: PrincipalType;
}
export interface Home {
  id: string;
  name: string;
  role: MembershipRole;
  relationship: HouseholdRelationship;
  permission_profile: PermissionProfile;
  capabilities: string[];
  member_count: number;
  // Shown to any member so an adult can hand it to a Child for sign-in.
  child_login_code: string;
}
export interface Member {
  membership_id: string;
  user_id: string;
  display_name: string;
  email: string | null;
  role: MembershipRole;
  relationship: HouseholdRelationship;
  permission_profile: PermissionProfile;
  permission_overrides: Record<string, boolean>;
  shared_resources: string[];
  colour: string | null;
  avatar_version: string | null;
}

export type RecurrencePattern =
  | "none"
  | "daily"
  | "weekly"
  | "monthly"
  | "yearly"
  | "weekdays";

export interface EventLabel {
  id: string;
  name: string;
  color: string;
  is_active: boolean;
  sort_order: number;
}

export interface EventOccurrence {
  occurrence_id: string;
  event_id: string;
  calendar_id: string;
  title: string;
  start_at: string;
  end_at: string;
  is_all_day: boolean;
  timezone: string;
  description: string | null;
  location_text: string | null;
  label: EventLabel | null;
  member_ids: string[];
  recurrence: RecurrencePattern;
  reminder_minutes: number | null;
  created_by: string;
  updated_at: string;
}

export interface EventPayload {
  title: string;
  start_at: string;
  end_at: string;
  timezone: string;
  is_all_day: boolean;
  description?: string | null;
  location_text?: string | null;
  label_id?: string | null;
  // Omitted defaults to the Home's primary calendar — see
  // HomeCalendar.commercial_access. Targeting a read-only-due-to-plan
  // calendar is rejected server-side.
  calendar_id?: string | null;
  member_ids?: string[];
  reminder_minutes?: number | null;
  recurrence?: RecurrencePattern;
  recurrence_interval?: number;
  recurrence_until?: string | null;
  recurrence_count?: number | null;
}

export type CalendarCommercialAccess = "normal" | "read_only_due_to_plan";

export interface HomeCalendar {
  id: string;
  name: string;
  timezone: string;
  is_primary: boolean;
  commercial_access: CalendarCommercialAccess;
  created_at: string;
}

export interface CalendarListResponse {
  items: HomeCalendar[];
  limit: number | null;
}

export interface CalendarUsage {
  count: number;
  limit: number | null;
  over_limit: boolean;
}

export interface EventUpdatePayload extends EventPayload {
  expected_updated_at: string;
}

export interface EventActivity {
  id: string;
  action: string;
  summary: string;
  actor_user_id: string | null;
  created_at: string;
}

export interface EventDetailResponse {
  event: EventOccurrence;
  activity: EventActivity[];
}

export interface EventListResponse {
  items: EventOccurrence[];
  next_page: number | null;
}

export interface InvitationResponse {
  id: string;
  group_id: string;
  email: string;
  role: MembershipRole;
  relationship: HouseholdRelationship;
  permission_profile: PermissionProfile;
  shared_resources: string[];
  expires_at: string;
}

export interface InvitationListItem extends InvitationResponse {
  accepted_at: string | null;
  revoked_at: string | null;
  inviter_display_name: string;
  join_link: string | null;
}

export interface InvitationPreview {
  group_id: string;
  group_name: string;
  invited_by_display_name: string;
  email: string;
  role: MembershipRole;
  relationship: HouseholdRelationship;
  expires_at: string;
}

export interface HomeSummary {
  home_name: string;
  member_count: number;
  pending_invitations: number | null;
  today_events: EventOccurrence[];
  next_event: EventOccurrence | null;
}

export type FeatureKey =
  | "calendar"
  | "tasks"
  | "shopping"
  | "meals"
  | "plans"
  | "wish_lists"
  | "notifications"
  | "external_sharing";

export interface FeatureEvaluation {
  feature: FeatureKey;
  enabled: boolean;
}

export interface FeatureMatrix {
  features: FeatureEvaluation[];
}

export type ReleaseState = "core" | "released" | "beta" | "hidden";

export interface HouseholdModule {
  id: string;
  name: string;
  description: string;
  category: string;
  release_state: ReleaseState;
  enabled: boolean;
  toggleable: boolean;
  introduced_version: string | null;
  dependencies: string[];
  permissions: string[];
  route: string | null;
}

export type ChildAgeBand = "under_13" | "13_to_15" | "16_to_17";
export type ChildTransitionStatus = "child" | "review_due" | "converted";

export interface ChildProfile {
  membership_id: string;
  user_id: string;
  display_name: string;
  age_band: ChildAgeBand;
  permissions: Record<string, boolean>;
  guardian_membership_ids: string[];
  transition_status: ChildTransitionStatus;
  birth_month: number | null;
  birth_day: number | null;
  birthday_visible: boolean;
  // Managed Child sign-in status. The username is shown back so the adult who
  // configured it can see it; the PIN is never returned by any endpoint.
  login_enabled: boolean;
  login_username: string | null;
}

export interface ChildLoginConfigurePayload {
  enabled: boolean;
  username?: string;
  pin?: string;
}

export interface ChildLoginRequest {
  home_code: string;
  username: string;
  pin: string;
}

export type LockScreenPreviewLevel = "full" | "title_only" | "hidden";
export type BriefingDays = "daily" | "weekdays";

export interface NotificationPreferences {
  push_enabled: boolean;
  in_app_enabled: boolean;
  email_enabled: boolean;
  event_reminders_enabled: boolean;
  event_invitations_enabled: boolean;
  event_changes_enabled: boolean;
  household_reminders_enabled: boolean;
  daily_briefing_enabled: boolean;
  briefing_time: string;
  briefing_days: BriefingDays;
  empty_day_briefing_enabled: boolean;
  lock_screen_preview_level: LockScreenPreviewLevel;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  quiet_hours_critical_only: boolean;
}

export interface PushSubscriptionSummary {
  id: string;
  device_label: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string | null;
  disabled_at: string | null;
}

export type RoutineReminderTiming = "evening_before" | "same_day" | "both";

export type RoutineScope = "personal" | "household";
export type RoutineRepeatUnit = "daily" | "weekly";

export interface Routine {
  id: string;
  title: string;
  description: string | null;
  scope: RoutineScope;
  owner_user_id: string | null;
  interval_weeks: number;
  repeat_unit: RoutineRepeatUnit;
  week_anchor_date: string;
  reminder_timing: RoutineReminderTiming;
  is_critical: boolean;
  pinned: boolean;
  enabled: boolean;
  start_date: string;
  end_date: string | null;
  member_ids: string[];
  next_occurrence_date: string | null;
  completed_today: boolean;
  created_by: string;
  updated_at: string;
}

export interface RoutinePayload {
  title: string;
  description?: string | null;
  scope: RoutineScope;
  interval_weeks: number;
  repeat_unit: RoutineRepeatUnit;
  week_anchor_date: string;
  reminder_timing: RoutineReminderTiming;
  is_critical: boolean;
  pinned: boolean;
  start_date: string;
  end_date?: string | null;
  member_ids: string[];
}

export interface RoutineUpdatePayload extends RoutinePayload {
  enabled: boolean;
  expected_updated_at: string;
}

export interface RoutineListResponse {
  items: Routine[];
}

export interface UserBirthdayPayload {
  birth_month: number | null;
  birth_day: number | null;
  birth_year?: number | null;
}

export interface ChildBirthdayPayload {
  birth_month: number | null;
  birth_day: number | null;
  birthday_visible: boolean;
  reason?: string;
  confirmed: true;
}

export interface BirthdayEntry {
  owner_type: "user" | "child";
  owner_id: string;
  display_name: string;
  month: number;
  day: number;
  next_occurrence_date: string;
}

export interface BirthdayListResponse {
  items: BirthdayEntry[];
}

// Commercial billing (Stripe, Phases 3–4) — mirrors mykhaya.billing_schemas.
// See docs/architecture/commercial-entitlements.md#stripe-provider-boundary.

export type BillingInterval = "month" | "year";
export type SubscriptionPlanValue = "free" | "family";
export type SubscriptionProviderValue = "free" | "complimentary" | "stripe" | "apple" | "google";
export type SubscriptionStatusValue =
  | "active"
  | "trialing"
  | "past_due"
  | "cancel_at_period_end"
  | "cancelled";

export interface SubscriptionPrice {
  currency: string;
  unit_amount: number;
  formatted_amount: string;
}

export interface BillingStatus {
  stored_plan: SubscriptionPlanValue;
  provider: SubscriptionProviderValue;
  status: SubscriptionStatusValue;
  effective_plan: SubscriptionPlanValue;
  effective_status_reason: string | null;
  billing_interval: BillingInterval | null;
  // The actual amount this Home's own subscription is billed — resolved
  // live from Stripe, reflecting a grandfathered price if applicable. Never
  // a hard-coded figure. Null unless the Home is Stripe-backed.
  price: SubscriptionPrice | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  complimentary_expires_at: string | null;
  can_manage_billing: boolean;
  has_stripe_customer: boolean;
  stripe_billing_available: boolean;
  calendar_usage: CalendarUsage;
  member_usage: CalendarUsage;
  household_routines_enabled: boolean;
  shared_events_enabled: boolean;
  external_invites_enabled: boolean;
}

export interface PricingOption {
  interval: BillingInterval;
  provider: string;
  currency: string;
  unit_amount: number;
  formatted_amount: string;
}

export interface FamilyPricing {
  plan: string;
  options: PricingOption[];
  annual_saving_formatted: string | null;
  // True only when the current provider prices make annual mathematically
  // cheaper than 12 monthly periods — never a hard-coded assumption.
  annual_is_best_value: boolean;
  // The Phase 7 billing kill switch. Pricing stays visible/informational
  // even when false — only Checkout creation is actually blocked
  // (server-side) — so use this to swap "Choose Family" for a "temporarily
  // paused" notice rather than hiding the price.
  acquisition_enabled: boolean;
}

export interface PlanComparisonRow {
  key: string;
  label: string;
  free_display: string;
  family_display: string;
}

export interface PlanComparison {
  rows: PlanComparisonRow[];
}
