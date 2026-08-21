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
  | "adult"
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
// The user-facing product name for this is "Biometric sign-in" — see
// apps/web/components/passkey-client.ts. `label` is a per-device name
// ("iPhone", "Work laptop"), not shown as the primary UX (see Security
// settings). `authenticator_attachment` is "platform" | "cross-platform" |
// null (older credential/unreported) — informational only.
export interface Passkey {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  authenticator_attachment: string | null;
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
  // This is the actual user-facing "event category" resource
  // calendar.max_categories governs — see HomeCalendar.commercial_access
  // for the equivalent on the separate, lower-level Calendar concept. Only
  // populated by the management listing (GET /event-labels) — null when
  // embedded on an event or returned from create/update.
  commercial_access: CalendarCommercialAccess | null;
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
  // This event's calendar's own colour — what it renders as when `label` is
  // null. A category's colour always takes precedence when one is set; this
  // is only the fallback, but always populated (never a frontend-hardcoded
  // default). Unaffected by Personal Calendar privacy — just a colour.
  calendar_color: string;
  member_ids: string[];
  recurrence: RecurrencePattern;
  recurrence_end_date?: string | null;
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
  recurrence_end_date?: string | null;
  recurrence_count?: number | null;
}

export type CalendarCommercialAccess = "normal" | "read_only_due_to_plan";

export interface HomeCalendar {
  id: string;
  name: string;
  timezone: string;
  is_primary: boolean;
  // Set only on `CalendarListResponse.personal_calendar` — null for every
  // shared/Home calendar in `items`. Non-null means this is that user's
  // private Personal Calendar (see docs/architecture — never
  // entitlement-gated, never another member's).
  owner_user_id: string | null;
  // Fallback colour for events on this calendar that carry no category
  // (label_id null). For the primary/"Home calendar" this is user-editable
  // (see api-client's updateCalendar); the calendar's `name` is not — it's
  // a fixed product concept, not user data.
  color: string;
  commercial_access: CalendarCommercialAccess;
  created_at: string;
}

export interface CalendarListResponse {
  // Shared/Home calendars only — never includes any Personal Calendar,
  // including the caller's own. See `personal_calendar` below.
  items: HomeCalendar[];
  limit: number | null;
  // The signed-in user's own Personal Calendar within this Home. Present
  // for adult members; null for a managed Child (see
  // apps/api/mykhaya/calendar_provisioning.py).
  personal_calendar: HomeCalendar | null;
}

export interface CalendarUsage {
  count: number;
  limit: number | null;
  over_limit: boolean;
}

// Deliberately excludes `calendar_id` — matching the backend's EventUpdate
// schema exactly (StrictModel, extra="forbid"). An event's calendar
// assignment (shared Home calendar vs. a Personal Calendar) is fixed at
// creation and never changes via edit; the backend always uses the
// existing CalendarEvent.calendar_id row for updates. Sending `calendar_id`
// on a PATCH is rejected with a 422 ("extra_forbidden") — see
// EventForm.submit/`update()` in app/calendar/page.tsx, which strips it
// before calling updateEvent.
export interface EventUpdatePayload extends Omit<EventPayload, "calendar_id"> {
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
  home_occurrence_date?: string | null;
  home_completed_at?: string | null;
  home_completed_by_user_id?: string | null;
  home_completed_by_display_name?: string | null;
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

// ---------------------------------------------------------------------------
// Meal Plans (Family-only)
// ---------------------------------------------------------------------------

export type MealType = "breakfast" | "lunch" | "dinner" | "snack" | "dessert" | "other";
export type MealSlot = "breakfast" | "lunch" | "dinner";

export interface MealIngredient {
  id: string;
  position: number;
  text: string;
  quantity: string | null;
  unit: string | null;
}

export interface MealIngredientInput {
  text: string;
  quantity?: string | null;
  unit?: string | null;
}

export interface Meal {
  id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  meal_type: MealType;
  prep_minutes: number | null;
  cook_minutes: number | null;
  servings: number | null;
  instructions: string | null;
  is_favourite: boolean;
  tags: string[];
  source_url: string | null;
  ingredients: MealIngredient[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MealPayload {
  name: string;
  description?: string | null;
  image_url?: string | null;
  meal_type?: MealType;
  prep_minutes?: number | null;
  cook_minutes?: number | null;
  servings?: number | null;
  instructions?: string | null;
  is_favourite?: boolean;
  tags?: string[];
  source_url?: string | null;
  ingredients?: MealIngredientInput[];
}

export interface MealUpdatePayload extends MealPayload {
  expected_updated_at: string;
}

// The Meals library list/recent views' shape — a meal card's worth of
// data, deliberately without the ingredient list (see
// mykhaya.schemas.MealSummaryResponse). Fetch the full Meal (via the detail
// endpoint) only when the ingredients/instructions are actually needed.
export interface MealSummary {
  id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  meal_type: MealType;
  prep_minutes: number | null;
  cook_minutes: number | null;
  servings: number | null;
  is_favourite: boolean;
  tags: string[];
  ingredient_count: number;
  created_at: string;
  updated_at: string;
}

export interface MealListResponse {
  items: MealSummary[];
}

export interface RecentMeal {
  meal: MealSummary;
  last_planned: string;
}

export interface RecentMealsResponse {
  items: RecentMeal[];
}

export interface MealPlanEntry {
  id: string;
  meal_id: string | null;
  meal_name: string | null;
  quick_meal_name: string | null;
  meal_image_url: string | null;
  is_favourite: boolean;
  date: string;
  meal_slot: MealSlot;
  time: string | null;
  member_ids: string[];
  cook_member_id: string | null;
  makes_leftovers: boolean;
  created_by: string;
  updated_at: string;
}

export interface MealPlanEntryPayload {
  meal_id?: string | null;
  quick_meal_name?: string | null;
  date: string;
  meal_slot: MealSlot;
  time?: string | null;
  // Omitted entirely means "Everyone" (the whole household) — an explicit
  // empty array means nobody. See mykhaya.routers.meal_plans.
  member_ids?: string[];
  cook_member_id?: string | null;
  makes_leftovers?: boolean;
}

export interface MealPlanEntryUpdatePayload extends MealPlanEntryPayload {
  expected_updated_at: string;
}

export interface MealPlanDay {
  date: string;
  entries: MealPlanEntry[];
}

export interface MealPlanWeek {
  start_date: string;
  days: MealPlanDay[];
}

export interface CopyWeekPayload {
  source_start_date: string;
  target_start_date: string;
  dry_run?: boolean;
}

export interface CopyWeekResult {
  copied_count: number;
  skipped_count: number;
}

export interface AddIngredientsToListPayload {
  list_id: string;
  ingredient_ids?: string[];
  confirm?: boolean;
}

export interface AddIngredientsToListResult {
  requires_confirmation: boolean;
  added_count: number;
  duplicate_count: number;
  duplicate_texts: string[];
  list_id: string;
}

// ---------------------------------------------------------------------------
// Household Lists — MyKhaya's one shared-list primitive (groceries,
// packing, DIY, school, party/Christmas/holiday prep, and Meal Plans' "Add
// ingredients to list" destination). See mykhaya.routers.lists and
// docs/architecture/lists.md.
// ---------------------------------------------------------------------------

// Presentation-only preset — mirrors mykhaya.schemas.LIST_ICONS.
export type ListIcon =
  | "groceries"
  | "shopping"
  | "packing"
  | "home"
  | "school"
  | "party"
  | "christmas"
  | "other";

export interface HouseholdListItem {
  id: string;
  position: number;
  text: string;
  quantity: string | null;
  note: string | null;
  assigned_member_id: string | null;
  is_checked: boolean;
  completed_at: string | null;
  completed_by: string | null;
}

export interface HouseholdList {
  id: string;
  name: string;
  icon: ListIcon | null;
  item_count: number;
  remaining_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface HouseholdListDetail {
  id: string;
  name: string;
  icon: ListIcon | null;
  items: HouseholdListItem[];
  item_count: number;
  remaining_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface HouseholdListListResponse {
  items: HouseholdList[];
}

export interface ListCreatePayload {
  name: string;
  icon?: ListIcon | null;
}

export interface ListRenamePayload {
  name: string;
  icon?: ListIcon | null;
  expected_updated_at: string;
}

export interface ListItemInputPayload {
  text: string;
  quantity?: string | null;
  note?: string | null;
  assigned_member_id?: string | null;
}

// Every field optional — only the ones present are applied server-side
// (see mykhaya.schemas.ListItemUpdate). A plain checkbox toggle sends only
// `is_checked`; an edit sends only the fields that changed.
export interface ListItemUpdatePayload {
  text?: string;
  quantity?: string | null;
  note?: string | null;
  assigned_member_id?: string | null;
  is_checked?: boolean;
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
  category_usage: CalendarUsage;
  member_usage: CalendarUsage;
  household_routines_enabled: boolean;
  shared_events_enabled: boolean;
  external_invites_enabled: boolean;
  meals_enabled: boolean;
  lists_enabled: boolean;
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
