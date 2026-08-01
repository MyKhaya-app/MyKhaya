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
export interface User {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
}
export interface Home {
  id: string;
  name: string;
  role: MembershipRole;
  relationship: HouseholdRelationship;
  permission_profile: PermissionProfile;
  capabilities: string[];
  member_count: number;
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
  member_ids?: string[];
  reminder_minutes?: number | null;
  recurrence?: RecurrencePattern;
  recurrence_interval?: number;
  recurrence_until?: string | null;
  recurrence_count?: number | null;
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
}
