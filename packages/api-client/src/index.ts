import type { Home, Member, User } from "@mykhaya/shared-types";
import { ApiError } from "./errors";
export { ApiError } from "./errors";

export class MyKhayaClient {
  constructor(private readonly baseUrl = "/api/v1") {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const csrf =
      typeof document === "undefined"
        ? undefined
        : document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1];
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    // Leave FormData bodies alone — the browser sets Content-Type itself, including
    // the multipart boundary, which we can't reproduce by hand.
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    if (csrf && !["GET", "HEAD", "OPTIONS"].includes(init.method ?? "GET"))
      headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        detail?: string;
      } | null;
      throw new ApiError(
        response.status,
        body?.detail ?? "Something went wrong. Please try again.",
      );
    }
    return response.status === 204
      ? (undefined as T)
      : (response.json() as Promise<T>);
  }

  me = () => this.request<User>("/users/me");
  updateMyBirthday = (
    body: import("@mykhaya/shared-types").UserBirthdayPayload,
  ) =>
    this.request<User>("/users/me/birthday", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  birthdays = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").BirthdayListResponse>(
      `/homes/${encodeURIComponent(homeId)}/birthdays`,
    );
  uploadAvatar = (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return this.request<User>("/users/me/avatar", { method: "POST", body });
  };
  removeAvatar = () => this.request<User>("/users/me/avatar", { method: "DELETE" });
  homes = () => this.request<Home[]>("/groups");
  members = (homeId: string) =>
    this.request<Member[]>(`/groups/${encodeURIComponent(homeId)}/members`);
  updateMemberColour = (homeId: string, userId: string, colour: string) =>
    this.request<Member>(
      `/groups/${encodeURIComponent(homeId)}/members/${encodeURIComponent(userId)}/colour`,
      { method: "PATCH", body: JSON.stringify({ colour }) },
    );
  homeSummary = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HomeSummary>(
      `/homes/${encodeURIComponent(homeId)}/summary`,
    );
  featureMatrix = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").FeatureMatrix>(
      `/features/${encodeURIComponent(homeId)}`,
    );
  featureManagement = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdModule[]>(
      `/features/${encodeURIComponent(homeId)}/modules/management`,
    );
  navigationModules = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdModule[]>(
      `/features/${encodeURIComponent(homeId)}/modules/navigation`,
    );
  updateHouseholdFeature = (
    homeId: string,
    feature: import("@mykhaya/shared-types").FeatureKey,
    body: { enabled: boolean; reason?: string; confirmed: true },
  ) =>
    this.request<import("@mykhaya/shared-types").HouseholdModule>(
      `/features/${encodeURIComponent(homeId)}/${encodeURIComponent(feature)}/household`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  children = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").ChildProfile[]>(
      `/groups/${encodeURIComponent(homeId)}/children`,
    );
  createChild = (
    homeId: string,
    body: {
      display_name: string;
      age_band: import("@mykhaya/shared-types").ChildAgeBand;
      guardian_membership_ids: string[];
    },
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateChildPermissions = (
    homeId: string,
    membershipId: string,
    body: {
      permissions: Record<string, boolean>;
      reason?: string;
      confirmed: true;
    },
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/permissions`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  updateChildAgeBand = (
    homeId: string,
    membershipId: string,
    body: {
      age_band: import("@mykhaya/shared-types").ChildAgeBand;
      reason?: string;
      confirmed: true;
    },
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/age-band`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  updateChildBirthday = (
    homeId: string,
    membershipId: string,
    body: import("@mykhaya/shared-types").ChildBirthdayPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/birthday`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  updateChildGuardians = (
    homeId: string,
    membershipId: string,
    body: {
      guardian_membership_ids: string[];
      reason?: string;
      confirmed: true;
    },
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/guardians`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  requestChildAdultReview = (
    homeId: string,
    membershipId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/adult-transition-review`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateChildLogin = (
    homeId: string,
    membershipId: string,
    body: import("@mykhaya/shared-types").ChildLoginConfigurePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/login`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  revokeChildSessions = (homeId: string, membershipId: string) =>
    this.request<import("@mykhaya/shared-types").ChildProfile>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}/login/revoke-sessions`,
      { method: "POST" },
    );
  childLogin = (body: import("@mykhaya/shared-types").ChildLoginRequest) =>
    this.request<User>("/auth/child/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
  anonymiseChild = (
    homeId: string,
    membershipId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<void>(
      `/groups/${encodeURIComponent(homeId)}/children/${encodeURIComponent(membershipId)}`,
      { method: "DELETE", body: JSON.stringify(body) },
    );
  listInvitations = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").InvitationListItem[]>(
      `/invitations/group/${encodeURIComponent(homeId)}`,
    );
  createLabel = (homeId: string, body: { name: string; color: string }) =>
    this.request<import("@mykhaya/shared-types").EventLabel>(
      `/homes/${encodeURIComponent(homeId)}/event-labels`,
      { method: "POST", body: JSON.stringify(body) },
    );
  listLabels = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").EventLabel[]>(
      `/homes/${encodeURIComponent(homeId)}/event-labels`,
    );
  updateLabel = (
    homeId: string,
    labelId: string,
    body: { name?: string; color?: string; is_active?: boolean },
  ) =>
    this.request<import("@mykhaya/shared-types").EventLabel>(
      `/homes/${encodeURIComponent(homeId)}/event-labels/${encodeURIComponent(labelId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  listEvents = (
    homeId: string,
    params: {
      start_at: string;
      end_at: string;
      page?: number;
      page_size?: number;
      q?: string;
    },
  ) => {
    const search = new URLSearchParams({
      start_at: params.start_at,
      end_at: params.end_at,
      page: String(params.page ?? 1),
      page_size: String(params.page_size ?? 200),
    });
    if (params.q) search.set("q", params.q);
    return this.request<import("@mykhaya/shared-types").EventListResponse>(
      `/homes/${encodeURIComponent(homeId)}/events?${search.toString()}`,
    );
  };
  createEvent = (
    homeId: string,
    body: import("@mykhaya/shared-types").EventPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").EventOccurrence>(
      `/homes/${encodeURIComponent(homeId)}/events`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateEvent = (
    homeId: string,
    eventId: string,
    body: import("@mykhaya/shared-types").EventUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").EventOccurrence>(
      `/homes/${encodeURIComponent(homeId)}/events/${encodeURIComponent(eventId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteEvent = (homeId: string, eventId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/events/${encodeURIComponent(eventId)}`,
      { method: "DELETE" },
    );
  eventDetail = (homeId: string, eventId: string) =>
    this.request<import("@mykhaya/shared-types").EventDetailResponse>(
      `/homes/${encodeURIComponent(homeId)}/events/${encodeURIComponent(eventId)}`,
    );
  previewInvitation = (token: string) =>
    this.request<import("@mykhaya/shared-types").InvitationPreview>(
      `/invitations/preview?token=${encodeURIComponent(token)}`,
    );
  resendInvitation = (invitationId: string) =>
    this.post<import("@mykhaya/shared-types").InvitationResponse>(
      "/invitations/resend",
      {
        invitation_id: invitationId,
      },
    );
  revokeInvitation = (invitationId: string) =>
    this.post<{ message: string }>("/invitations/revoke", {
      invitation_id: invitationId,
    });
  pushPublicKey = () =>
    this.request<{ configured: boolean; public_key: string | null }>(
      "/notifications/push/public-key",
    );
  listPushSubscriptions = () =>
    this.request<import("@mykhaya/shared-types").PushSubscriptionSummary[]>(
      "/notifications/push-subscriptions",
    );
  registerPushSubscription = (body: {
    endpoint: string;
    keys: { p256dh: string; auth: string };
    device_label?: string | null;
    user_agent?: string | null;
  }) =>
    this.request<{ id: string }>("/notifications/push-subscriptions", {
      method: "POST",
      body: JSON.stringify(body),
    });
  deletePushSubscription = (subscriptionId: string) =>
    this.request<void>(
      `/notifications/push-subscriptions/${encodeURIComponent(subscriptionId)}`,
      { method: "DELETE" },
    );
  notificationPreferences = () =>
    this.request<import("@mykhaya/shared-types").NotificationPreferences>(
      "/notifications/preferences",
    );
  updateNotificationPreferences = (
    body: import("@mykhaya/shared-types").NotificationPreferences,
  ) =>
    this.request<import("@mykhaya/shared-types").NotificationPreferences>(
      "/notifications/preferences",
      { method: "PUT", body: JSON.stringify(body) },
    );
  routines = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").RoutineListResponse>(
      `/homes/${encodeURIComponent(homeId)}/routines`,
    );
  createRoutine = (
    homeId: string,
    body: import("@mykhaya/shared-types").RoutinePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").Routine>(
      `/homes/${encodeURIComponent(homeId)}/routines`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateRoutine = (
    homeId: string,
    routineId: string,
    body: import("@mykhaya/shared-types").RoutineUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").Routine>(
      `/homes/${encodeURIComponent(homeId)}/routines/${encodeURIComponent(routineId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteRoutine = (homeId: string, routineId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/routines/${encodeURIComponent(routineId)}`,
      { method: "DELETE" },
    );
  completeRoutine = (homeId: string, routineId: string, occurrenceDate: string) =>
    this.request<import("@mykhaya/shared-types").Routine>(
      `/homes/${encodeURIComponent(homeId)}/routines/${encodeURIComponent(routineId)}/complete`,
      { method: "POST", body: JSON.stringify({ occurrence_date: occurrenceDate }) },
    );
  uncompleteRoutine = (homeId: string, routineId: string, occurrenceDate: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/routines/${encodeURIComponent(routineId)}/complete/${encodeURIComponent(occurrenceDate)}`,
      { method: "DELETE" },
    );
  post = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  patch = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  put = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  delete = (path: string) => this.request<void>(path, { method: "DELETE" });
}

export const api = new MyKhayaClient();

export { platformApi, PlatformClient } from "./platform";
