import type { Home, Member, User } from "@mykhaya/shared-types";
import { ApiError } from "./errors";
export { ApiError } from "./errors";

export type ConsumerMfaStatus = {
  required: boolean;
  allowed_methods: ("totp" | "email")[];
  email_available: boolean;
  email_destination: string | null;
  totp_enabled: boolean;
  can_disable_totp: boolean;
  usable_methods: ("totp" | "email")[];
  preferred_method: "totp" | "email" | null;
};

export type BudgetProfile = {
  id: string;
  owner_user_id: string;
  currency: string;
  month_start_day: number;
  archived: boolean;
};

export type BudgetCategory = {
  id: string;
  name: string;
  sort_order: number;
  archived: boolean;
};

export type BudgetMonthCategory = {
  id: string;
  category_id: string;
  category_name: string;
  planned_amount: number;
  actual_source: "manual" | "entries";
  manual_actual: number | null;
  entries_actual: number;
  actual_amount: number;
};

export type BudgetMonthIncome = {
  id: string;
  source_id: string;
  source_name: string;
  expected_amount: number;
  received_amount: number;
};

export type BudgetMonth = {
  id: string;
  year: number;
  month: number;
  categories: BudgetMonthCategory[];
  income: BudgetMonthIncome[];
};

export type BudgetIncomeSource = {
  id: string;
  name: string;
  sort_order: number;
  archived: boolean;
};

export type BudgetSpendingEntry = {
  id: string;
  category_id: string;
  description: string;
  amount: number;
  spent_on: string;
};

export type BudgetPartnerShare = {
  id: string;
  partner_user_id: string;
  level: "summary" | "categories" | "full";
  active: boolean;
};

export type BudgetIncomingShare = {
  home_id: string;
  owner_user_id: string;
  owner_display_name: string;
  level: "summary" | "categories" | "full";
};

function isFormDataBody(body: BodyInit | null | undefined): boolean {
  return Boolean(body && Object.prototype.toString.call(body) === "[object FormData]");
}

export class MyKhayaClient {
  constructor(private readonly baseUrl = "/api/v1") {}

  private requestTransport:
    | (<T>(path: string, init?: RequestInit) => Promise<T>)
    | undefined;

  /** Install the native bearer transport for the Capacitor shell. A null
   * transport restores the ordinary browser/PWA cookie transport. */
  setRequestTransport(
    transport: (<T>(path: string, init?: RequestInit) => Promise<T>) | null,
  ): void {
    this.requestTransport = transport ?? undefined;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (this.requestTransport) return this.requestTransport<T>(path, init);
    // Guest wishlist endpoints (`/wishlist/share/...verify`, `/wishlist/guest/...`)
    // use a separate, lower-privileged cookie pair (mk_wishlist_guest /
    // mk_wishlist_guest_csrf, see wishlist_guest.py) that is never the normal
    // mk_session/mk_csrf pair a signed-in member's requests use — a guest never
    // has a MyKhaya session at all. Branching on the path here (rather than a
    // second client class) keeps every wishlist call, guest or member, going
    // through the same request()/error-handling/credentials logic; the only
    // thing that differs for guest paths is which CSRF cookie is read.
    const csrfCookieName =
      path === "/auth/renew"
        ? "mk_device_csrf"
        : path.startsWith("/wishlist/guest") || path.startsWith("/wishlist/share")
          ? "mk_wishlist_guest_csrf"
          : "mk_csrf";
    const csrf =
      typeof document === "undefined"
        ? undefined
        : document.cookie.match(new RegExp(`(?:^|; )${csrfCookieName}=([^;]+)`))?.[1];
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    // Leave FormData bodies alone — the browser sets Content-Type itself, including
    // the multipart boundary, which we can't reproduce by hand.
    if (init.body && !isFormDataBody(init.body)) {
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
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = body?.detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const { code, message, ...metadata } = detail as {
          code?: string;
          message: string;
          [key: string]: unknown;
        };
        throw new ApiError(response.status, message, code, metadata);
      }
      throw new ApiError(
        response.status,
        typeof detail === "string" ? detail : "Something went wrong. Please try again.",
      );
    }
    return response.status === 204
      ? (undefined as T)
      : (response.json() as Promise<T>);
  }

  me = () => this.request<User>("/users/me");
  activityHeartbeat = () =>
    this.request<void>("/activity/heartbeat", { method: "POST", body: "{}" });
  productUsageEvent = (body: {
    event_name: import("@mykhaya/shared-types").ProductUsageEventName;
    platform: import("@mykhaya/shared-types").ProductUsagePlatform;
    module?: import("@mykhaya/shared-types").ProductUsageModule;
    home_id?: string;
    app_version?: string;
    usage_session_id?: string;
    event_key?: string;
  }) => this.request<{ status: string }>("/usage/events", {
    method: "POST",
    body: JSON.stringify(body),
  });
  authProviders = () =>
    this.request<{ providers: Array<{ provider: string; enabled: boolean }> }>(
      "/auth/providers",
    );
  renew = () => this.request<User>("/auth/renew", { method: "POST", body: "{}" });
  devices = () =>
    this.request<{
      id: string;
      created_at: string;
      last_used_at: string;
      expires_at: string;
      device_name: string;
      platform: string;
      user_agent: string;
      current: boolean;
    }[]>("/auth/devices");
  revokeDevice = (deviceId: string) =>
    this.request<void>(`/auth/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
  revokeOtherDevices = () =>
    this.request<void>("/auth/devices/revoke-others", { method: "POST", body: "{}" });
  passkeyLoginOptions = () =>
    this.request<{ options_json: string }>("/auth/passkeys/login/options", {
      method: "POST",
      body: "{}",
    });
  passkeyLoginVerify = (credentialJson: string) =>
    this.request<User>("/auth/passkeys/login/verify", {
      method: "POST",
      body: JSON.stringify({ credential_json: credentialJson }),
    });
  passkeys = () =>
    this.request<import("@mykhaya/shared-types").Passkey[]>("/auth/passkeys");
  passkeyRegistrationOptions = () =>
    this.request<{ options_json: string }>("/auth/passkeys/register/options", {
      method: "POST",
      body: "{}",
    });
  passkeyRegistrationVerify = (credentialJson: string, label?: string) =>
    this.request<import("@mykhaya/shared-types").Passkey>("/auth/passkeys/register/verify", {
      method: "POST",
      body: JSON.stringify({ credential_json: credentialJson, label }),
    });
  renamePasskey = (id: string, label: string) =>
    this.request<import("@mykhaya/shared-types").Passkey>(
      `/auth/passkeys/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify({ label }) },
    );
  revokePasskey = (id: string) =>
    this.request<void>(`/auth/passkeys/${encodeURIComponent(id)}`, { method: "DELETE" });
  mfaStatus = () =>
    this.request<ConsumerMfaStatus>("/auth/mfa/status");
  setMfaPreference = (method: "totp" | "email" | null) =>
    this.request<ConsumerMfaStatus>("/auth/mfa/preference", {
      method: "PATCH",
      body: JSON.stringify({ method }),
    });
  reauthenticate = (password: string) =>
    this.request<void>("/auth/reauthenticate", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
  totpSetup = () =>
    this.request<{
      method: "totp";
      provisioning_uri: string;
      manual_key: string;
      enrolling: boolean;
    }>("/auth/mfa/totp/setup", { method: "POST", body: "{}" });
  totpVerify = (code: string) =>
    this.request<ConsumerMfaStatus>("/auth/mfa/totp/verify", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  removeTotp = () => this.request<void>("/auth/mfa/totp", { method: "DELETE" });
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
    console.debug("[avatar-upload] formdata-created", {
      field: "file",
      fileType: file.type || "(empty)",
      fileSize: file.size,
    });
    return this.request<User>("/users/me/avatar", { method: "POST", body });
  };
  removeAvatar = () => this.request<User>("/users/me/avatar", { method: "DELETE" });
  uploadMemberAvatar = (homeId: string, userId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return this.request<Member>(
      `/groups/${encodeURIComponent(homeId)}/members/${encodeURIComponent(userId)}/avatar`,
      { method: "POST", body },
    );
  };
  removeMemberAvatar = (homeId: string, userId: string) =>
    this.request<Member>(
      `/groups/${encodeURIComponent(homeId)}/members/${encodeURIComponent(userId)}/avatar`,
      { method: "DELETE" },
    );
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
  budgetProfile = (homeId: string) =>
    this.request<BudgetProfile>(`/homes/${encodeURIComponent(homeId)}/budget`);
  budgetSettings = (homeId: string) =>
    this.request<BudgetProfile>(`/homes/${encodeURIComponent(homeId)}/budget/settings`);
  updateBudgetSettings = (
    homeId: string,
    body: { currency: string; month_start_day: number },
  ) =>
    this.request<BudgetProfile>(`/homes/${encodeURIComponent(homeId)}/budget/settings`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  budgetCategories = (homeId: string) =>
    this.request<BudgetCategory[]>(`/homes/${encodeURIComponent(homeId)}/budget/categories`);
  createBudgetCategory = (
    homeId: string,
    body: { name: string; sort_order?: number; year?: number; month?: number },
  ) =>
    this.request<BudgetCategory>(`/homes/${encodeURIComponent(homeId)}/budget/categories`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  budgetIncomeSources = (homeId: string) =>
    this.request<BudgetIncomeSource[]>(
      `/homes/${encodeURIComponent(homeId)}/budget/income-sources`,
    );
  createBudgetIncomeSource = (
    homeId: string,
    body: { name: string; sort_order?: number; year?: number; month?: number },
  ) =>
    this.request<BudgetIncomeSource>(
      `/homes/${encodeURIComponent(homeId)}/budget/income-sources`,
      { method: "POST", body: JSON.stringify(body) },
    );
  budgetMonth = (homeId: string, year: number, month: number) =>
    this.request<BudgetMonth>(
      `/homes/${encodeURIComponent(homeId)}/budget/months/${year}/${month}`,
    );
  createBudgetMonth = (homeId: string, year: number, month: number) =>
    this.request<BudgetMonth>(
      `/homes/${encodeURIComponent(homeId)}/budget/months/${year}/${month}`,
      { method: "POST", body: "{}" },
    );
  createBudgetEntry = (
    homeId: string,
    body: { category_id: string; description: string; amount: number; spent_on: string },
  ) =>
    this.request<BudgetSpendingEntry>(`/homes/${encodeURIComponent(homeId)}/budget/entries`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  budgetEntries = (homeId: string, params?: { year?: number; month?: number }) => {
    const search = new URLSearchParams();
    if (params?.year !== undefined) search.set("year", String(params.year));
    if (params?.month !== undefined) search.set("month", String(params.month));
    const suffix = search.toString() ? `?${search.toString()}` : "";
    return this.request<BudgetSpendingEntry[]>(
      `/homes/${encodeURIComponent(homeId)}/budget/entries${suffix}`,
    );
  };
  budgetEntry = (homeId: string, entryId: string) =>
    this.request<BudgetSpendingEntry>(
      `/homes/${encodeURIComponent(homeId)}/budget/entries/${encodeURIComponent(entryId)}`,
    );
  updateBudgetEntry = (
    homeId: string,
    entryId: string,
    body: { category_id: string; description: string; amount: number; spent_on: string },
  ) =>
    this.request<BudgetSpendingEntry>(
      `/homes/${encodeURIComponent(homeId)}/budget/entries/${encodeURIComponent(entryId)}`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  deleteBudgetEntry = (homeId: string, entryId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/budget/entries/${encodeURIComponent(entryId)}`,
      { method: "DELETE" },
    );
  updateBudgetActual = (
    homeId: string,
    year: number,
    month: number,
    categoryId: string,
    body: { source: "manual" | "entries"; manual_actual?: number },
  ) =>
    this.request<BudgetMonthCategory>(
      `/homes/${encodeURIComponent(homeId)}/budget/months/${year}/${month}/categories/${encodeURIComponent(categoryId)}/actual`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  updateBudgetPlan = (
    homeId: string,
    year: number,
    month: number,
    categoryId: string,
    plannedAmount: number,
  ) =>
    this.request<BudgetMonthCategory>(
      `/homes/${encodeURIComponent(homeId)}/budget/months/${year}/${month}/categories/${encodeURIComponent(categoryId)}/plan`,
      { method: "PUT", body: JSON.stringify({ planned_amount: plannedAmount }) },
    );
  updateBudgetMonthIncome = (
    homeId: string,
    year: number,
    month: number,
    sourceId: string,
    body: { expected_amount: number; received_amount: number },
  ) =>
    this.request<BudgetMonthIncome>(
      `/homes/${encodeURIComponent(homeId)}/budget/months/${year}/${month}/income/${encodeURIComponent(sourceId)}`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  budgetShares = (homeId: string) =>
    this.request<BudgetPartnerShare[]>(`/homes/${encodeURIComponent(homeId)}/budget/shares`);
  setBudgetShare = (
    homeId: string,
    partnerUserId: string,
    level: BudgetPartnerShare["level"],
  ) =>
    this.request<BudgetPartnerShare>(
      `/homes/${encodeURIComponent(homeId)}/budget/shares/${encodeURIComponent(partnerUserId)}`,
      { method: "PUT", body: JSON.stringify({ partner_user_id: partnerUserId, level }) },
    );
  revokeBudgetShare = (homeId: string, partnerUserId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/budget/shares/${encodeURIComponent(partnerUserId)}`,
      { method: "DELETE" },
    );
  incomingBudgetShares = (homeId: string) =>
    this.request<BudgetIncomingShare[]>(
      `/homes/${encodeURIComponent(homeId)}/budget/shared-with-me`,
    );
  sharedBudgetMonth = (
    homeId: string,
    ownerUserId: string,
    year: number,
    month: number,
  ) =>
    this.request<BudgetMonth>(
      `/homes/${encodeURIComponent(homeId)}/budget/shared/${encodeURIComponent(ownerUserId)}/months/${year}/${month}`,
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
  getHomeJoinCode = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HomeJoinCode>(
      `/groups/${encodeURIComponent(homeId)}/join-code`,
    );
  regenerateHomeJoinCode = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HomeJoinCode>(
      `/groups/${encodeURIComponent(homeId)}/join-code/regenerate`,
      { method: "POST" },
    );
  listHomeJoinRequests = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HomeJoinRequestListItem[]>(
      `/groups/${encodeURIComponent(homeId)}/join-requests`,
    );
  approveHomeJoinRequest = (
    homeId: string,
    requestId: string,
    body: {
      relationship: import("@mykhaya/shared-types").HouseholdRelationship;
      family_sponsorship: boolean;
      reason?: string;
      confirmed: true;
    },
  ) =>
    this.request<Member>(
      `/groups/${encodeURIComponent(homeId)}/join-requests/${encodeURIComponent(requestId)}/approve`,
      { method: "POST", body: JSON.stringify(body) },
    );
  declineHomeJoinRequest = (
    homeId: string,
    requestId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<void>(
      `/groups/${encodeURIComponent(homeId)}/join-requests/${encodeURIComponent(requestId)}/decline`,
      { method: "POST", body: JSON.stringify(body) },
    );
  lookupHomeJoinCode = (code: string) =>
    this.request<import("@mykhaya/shared-types").HomeJoinCodeLookup>("/home-join/lookup", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  requestHomeJoin = (code: string) =>
    this.request<import("@mykhaya/shared-types").HomeJoinRequestSummary>("/home-join/request", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  createLabel = (homeId: string, body: { name: string; color: string }) =>
    this.request<import("@mykhaya/shared-types").EventLabel>(
      `/homes/${encodeURIComponent(homeId)}/event-labels`,
      { method: "POST", body: JSON.stringify(body) },
    );
  listLabels = (homeId: string, options?: { includeInactive?: boolean }) =>
    this.request<import("@mykhaya/shared-types").EventLabel[]>(
      `/homes/${encodeURIComponent(homeId)}/event-labels${
        options?.includeInactive ? "?include_inactive=true" : ""
      }`,
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
  labelUsage = (homeId: string, labelId: string) =>
    this.request<import("@mykhaya/shared-types").EventLabelUsage>(
      `/homes/${encodeURIComponent(homeId)}/event-labels/${encodeURIComponent(labelId)}/usage`,
    );
  deleteLabel = (homeId: string, labelId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/event-labels/${encodeURIComponent(labelId)}`,
      { method: "DELETE" },
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
  listUpcomingEvents = (
    homeId: string,
    params: { after: string; limit?: number },
  ) => {
    const search = new URLSearchParams({ after: params.after });
    if (params.limit) search.set("limit", String(params.limit));
    return this.request<import("@mykhaya/shared-types").EventListResponse>(
      `/homes/${encodeURIComponent(homeId)}/events/upcoming?${search.toString()}`,
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
  deleteEvent = (
    homeId: string,
    eventId: string,
    scope?: import("@mykhaya/shared-types").EventMutationScope,
    occurrenceStart?: string,
  ) => {
    const search = new URLSearchParams();
    if (scope) search.set("scope", scope);
    if (occurrenceStart) search.set("occurrence_start", occurrenceStart);
    const query = search.toString();
    return this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/events/${encodeURIComponent(eventId)}${query ? `?${query}` : ""}`,
      { method: "DELETE" },
    );
  };
  listCalendars = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").CalendarListResponse>(
      `/homes/${encodeURIComponent(homeId)}/calendars`,
    );
  calendarHighlights = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").CalendarHighlightSettings>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights`,
    );
  updateCalendarHighlights = (homeId: string, birthdaysEnabled: boolean) =>
    this.request<import("@mykhaya/shared-types").CalendarHighlightSettings>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights`,
      { method: "PUT", body: JSON.stringify({ birthdays_enabled: birthdaysEnabled }) },
    );
  addHolidayCalendar = (homeId: string, sourceId: string) =>
    this.request<import("@mykhaya/shared-types").CalendarHighlightSettings["subscriptions"][number]>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights/holiday-calendars`,
      { method: "POST", body: JSON.stringify({ source_id: sourceId }) },
    );
  updateHolidayCalendar = (homeId: string, subscriptionId: string, enabled: boolean) =>
    this.request<import("@mykhaya/shared-types").CalendarHighlightSettings["subscriptions"][number]>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights/holiday-calendars/${encodeURIComponent(subscriptionId)}`,
      { method: "PATCH", body: JSON.stringify({ enabled }) },
    );
  removeHolidayCalendar = (homeId: string, subscriptionId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights/holiday-calendars/${encodeURIComponent(subscriptionId)}`,
      { method: "DELETE", body: "{}" },
    );
  calendarHighlightDates = (homeId: string, startDate: string, endDate: string) =>
    this.request<{ items: import("@mykhaya/shared-types").CalendarHighlight[] }>(
      `/homes/${encodeURIComponent(homeId)}/calendar-highlights/dates?${new URLSearchParams({ start_date: startDate, end_date: endDate })}`,
    );
  createCalendar = (homeId: string, body: { name: string; timezone?: string | null }) =>
    this.request<import("@mykhaya/shared-types").HomeCalendar>(
      `/homes/${encodeURIComponent(homeId)}/calendars`,
      { method: "POST", body: JSON.stringify(body) },
    );
  deleteCalendar = (
    homeId: string,
    calendarId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/calendars/${encodeURIComponent(calendarId)}`,
      { method: "DELETE", body: JSON.stringify(body) },
    );
  updateCalendar = (homeId: string, calendarId: string, body: { color: string }) =>
    this.request<import("@mykhaya/shared-types").HomeCalendar>(
      `/homes/${encodeURIComponent(homeId)}/calendars/${encodeURIComponent(calendarId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  eventDetail = (homeId: string, eventId: string) =>
    this.request<import("@mykhaya/shared-types").EventDetailResponse>(
      `/homes/${encodeURIComponent(homeId)}/events/${encodeURIComponent(eventId)}`,
    );
  // External Calendar Sharing — see apps/api/mykhaya/routers/calendar_sharing.py.
  createCalendarShare = (
    homeId: string,
    body: {
      calendar_id: string;
      recipient_email: string;
      permission: import("@mykhaya/shared-types").CalendarSharePermission;
      // Omit/undefined = share the entire calendar. A list = only those
      // categories — see CalendarShare.category_ids.
      category_ids?: string[] | null;
    },
  ) =>
    this.request<import("@mykhaya/shared-types").CalendarShare>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares`,
      { method: "POST", body: JSON.stringify(body) },
    );
  approveCalendarShare = (homeId: string, shareId: string) =>
    this.request<import("@mykhaya/shared-types").CalendarShare>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares/${encodeURIComponent(shareId)}/approve`,
      { method: "POST", body: "{}" },
    );
  listSharesForCalendar = (homeId: string, calendarId: string) =>
    this.request<{ items: import("@mykhaya/shared-types").CalendarShare[] }>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares/calendar/${encodeURIComponent(calendarId)}`,
    );
  changeCalendarSharePermission = (
    homeId: string,
    shareId: string,
    permission: import("@mykhaya/shared-types").CalendarSharePermission,
  ) =>
    this.request<import("@mykhaya/shared-types").CalendarShare>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares/${encodeURIComponent(shareId)}/permission`,
      { method: "POST", body: JSON.stringify({ permission }) },
    );
  changeCalendarShareCategories = (homeId: string, shareId: string, categoryIds: string[] | null) =>
    this.request<import("@mykhaya/shared-types").CalendarShare>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares/${encodeURIComponent(shareId)}/categories`,
      { method: "POST", body: JSON.stringify({ category_ids: categoryIds }) },
    );
  revokeCalendarShare = (homeId: string, shareId: string) =>
    this.request<{ message: string }>(
      `/homes/${encodeURIComponent(homeId)}/calendar-shares/${encodeURIComponent(shareId)}/revoke`,
      { method: "POST", body: "{}" },
    );
  previewCalendarShare = (token: string) =>
    this.request<import("@mykhaya/shared-types").CalendarSharePreview>(
      `/calendar-shares/preview?token=${encodeURIComponent(token)}`,
    );
  acceptCalendarShare = (
    token: string,
    body: { notification_preference: "all" | "important" | "off"; include_in_briefing: boolean },
  ) =>
    this.request<{ message: string }>("/calendar-shares/accept", {
      method: "POST",
      body: JSON.stringify({ token, ...body }),
    });
  declineCalendarShare = (token: string) =>
    this.request<{ message: string }>("/calendar-shares/decline", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  sharedCalendars = () =>
    this.request<{ items: import("@mykhaya/shared-types").CalendarShare[] }>(
      "/calendar-shares/mine",
    );
  updateCalendarSharePreferences = (
    shareId: string,
    body: { notification_preference?: "all" | "important" | "off"; include_in_briefing?: boolean },
  ) =>
    this.request<import("@mykhaya/shared-types").CalendarShare>(
      `/calendar-shares/${encodeURIComponent(shareId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  leaveCalendarShare = (shareId: string) =>
    this.request<{ message: string }>(
      `/calendar-shares/${encodeURIComponent(shareId)}/leave`,
      { method: "POST", body: "{}" },
    );
  listSharedEvents = (shareId: string, params: { start_at: string; end_at: string }) =>
    this.request<import("@mykhaya/shared-types").EventListResponse>(
      `/calendar-shares/${encodeURIComponent(shareId)}/events?${new URLSearchParams(params).toString()}`,
    );
  listUpcomingSharedEvents = (
    shareId: string,
    params: { after: string; limit?: number },
  ) => {
    const search = new URLSearchParams({ after: params.after });
    if (params.limit) search.set("limit", String(params.limit));
    return this.request<import("@mykhaya/shared-types").EventListResponse>(
      `/calendar-shares/${encodeURIComponent(shareId)}/events/upcoming?${search.toString()}`,
    );
  };
  createSharedEvent = (
    shareId: string,
    body: import("@mykhaya/shared-types").SharedEventPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").EventOccurrence>(
      `/calendar-shares/${encodeURIComponent(shareId)}/events`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateSharedEvent = (
    shareId: string,
    eventId: string,
    body: import("@mykhaya/shared-types").SharedEventUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").EventOccurrence>(
      `/calendar-shares/${encodeURIComponent(shareId)}/events/${encodeURIComponent(eventId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteSharedEvent = (shareId: string, eventId: string) =>
    this.request<void>(
      `/calendar-shares/${encodeURIComponent(shareId)}/events/${encodeURIComponent(eventId)}`,
      { method: "DELETE" },
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
  registerNativePushDevice = (body: {
    platform: "ios" | "android";
    token: string;
    installation_id: string;
    device_label?: string;
    apns_environment?: "sandbox" | "production";
  }) => this.request<{ id: string }>("/notifications/native-devices", { method: "POST", body: JSON.stringify(body) });
  deleteNativePushDevice = (deviceId: string) =>
    this.request<void>(`/notifications/native-devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
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
  notifications = (params?: {
    page?: number;
    filter?: "all" | "unread";
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.page !== undefined) query.set("page", String(params.page));
    if (params?.filter) query.set("filter", params.filter);
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request<import("@mykhaya/shared-types").NotificationListResponse>(
      `/notifications${suffix}`,
    );
  };
  notificationUnreadCount = () =>
    this.request<{ unread_count: number }>("/notifications/unread-count");
  markNotificationRead = (notificationId: string) =>
    this.request<{ message: string }>(
      `/notifications/${encodeURIComponent(notificationId)}/read`,
      { method: "POST" },
    );
  clearNotification = (notificationId: string) =>
    this.request<{ message: string }>(
      `/notifications/${encodeURIComponent(notificationId)}/clear`,
      { method: "POST" },
    );
  markAllNotificationsRead = () =>
    this.request<{ message: string }>("/notifications/read-all", { method: "POST" });
  clearAllNotifications = () =>
    this.request<{ message: string }>("/notifications/clear-all", { method: "POST" });
  routines = (homeId: string, params?: { home?: boolean }) =>
    this.request<import("@mykhaya/shared-types").RoutineListResponse>(
      `/homes/${encodeURIComponent(homeId)}/routines${params?.home ? "?home=true" : ""}`,
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
  reminders = (homeId: string, params?: { home?: boolean }) =>
    this.request<import("@mykhaya/shared-types").ReminderListResponse>(
      `/homes/${encodeURIComponent(homeId)}/reminders${params?.home ? "?home=true" : ""}`,
    );
  createReminder = (
    homeId: string,
    body: import("@mykhaya/shared-types").ReminderPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").Reminder>(
      `/homes/${encodeURIComponent(homeId)}/reminders`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateReminder = (
    homeId: string,
    reminderId: string,
    body: import("@mykhaya/shared-types").ReminderUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").Reminder>(
      `/homes/${encodeURIComponent(homeId)}/reminders/${encodeURIComponent(reminderId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteReminder = (homeId: string, reminderId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/reminders/${encodeURIComponent(reminderId)}`,
      { method: "DELETE" },
    );
  completeReminder = (homeId: string, reminderId: string, occurrenceDate: string) =>
    this.request<import("@mykhaya/shared-types").Reminder>(
      `/homes/${encodeURIComponent(homeId)}/reminders/${encodeURIComponent(reminderId)}/complete`,
      { method: "POST", body: JSON.stringify({ occurrence_date: occurrenceDate }) },
    );
  uncompleteReminder = (homeId: string, reminderId: string, occurrenceDate: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/reminders/${encodeURIComponent(reminderId)}/complete/${encodeURIComponent(occurrenceDate)}`,
      { method: "DELETE" },
    );
  todos = (homeId: string, params?: { include_completed?: boolean }) => {
    const query = params?.include_completed === undefined
      ? ""
      : `?include_completed=${String(params.include_completed)}`;
    return this.request<import("@mykhaya/shared-types").TodoListResponse>(
      `/homes/${encodeURIComponent(homeId)}/todos${query}`,
    );
  };
  createTodo = (homeId: string, body: import("@mykhaya/shared-types").TodoPayload) =>
    this.request<import("@mykhaya/shared-types").Todo>(
      `/homes/${encodeURIComponent(homeId)}/todos`,
      { method: "POST", body: JSON.stringify(body) },
    );
  grantFamilySponsorship = (
    homeId: string,
    userId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<import("@mykhaya/shared-types").Member>(
      `/groups/${encodeURIComponent(homeId)}/members/${encodeURIComponent(userId)}/family-sponsorship`,
      { method: "POST", body: JSON.stringify(body) },
    );
  revokeFamilySponsorship = (
    homeId: string,
    userId: string,
    body: { reason?: string; confirmed: true },
  ) =>
    this.request<import("@mykhaya/shared-types").Member>(
      `/groups/${encodeURIComponent(homeId)}/members/${encodeURIComponent(userId)}/family-sponsorship`,
      { method: "DELETE", body: JSON.stringify(body) },
    );
  updateTodo = (homeId: string, todoId: string, body: import("@mykhaya/shared-types").TodoUpdatePayload) =>
    this.request<import("@mykhaya/shared-types").Todo>(
      `/homes/${encodeURIComponent(homeId)}/todos/${encodeURIComponent(todoId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteTodo = (homeId: string, todoId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/todos/${encodeURIComponent(todoId)}`,
      { method: "DELETE" },
    );
  completeTodo = (homeId: string, todoId: string, completed = true) =>
    this.request<import("@mykhaya/shared-types").Todo>(
      `/homes/${encodeURIComponent(homeId)}/todos/${encodeURIComponent(todoId)}/complete`,
      { method: "POST", body: JSON.stringify({ completed }) },
    );
  todoCategories = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").TodoCategoryListResponse>(
      `/homes/${encodeURIComponent(homeId)}/todo-categories`,
    );
  createTodoCategory = (homeId: string, name: string) =>
    this.request<import("@mykhaya/shared-types").TodoCategory>(
      `/homes/${encodeURIComponent(homeId)}/todo-categories`,
      { method: "POST", body: JSON.stringify({ name }) },
    );
  updateTodoCategory = (homeId: string, categoryId: string, name: string, expected_updated_at: string) =>
    this.request<import("@mykhaya/shared-types").TodoCategory>(
      `/homes/${encodeURIComponent(homeId)}/todo-categories/${encodeURIComponent(categoryId)}`,
      { method: "PATCH", body: JSON.stringify({ name, expected_updated_at }) },
    );
  deleteTodoCategory = (homeId: string, categoryId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/todo-categories/${encodeURIComponent(categoryId)}`,
      { method: "DELETE" },
    );
  // --- Meal Plans (Family-only) -------------------------------------------
  meals = (homeId: string, params?: { favourite?: boolean; q?: string }) => {
    const search = new URLSearchParams();
    if (params?.favourite !== undefined) search.set("favourite", String(params.favourite));
    if (params?.q) search.set("q", params.q);
    const query = search.toString();
    return this.request<import("@mykhaya/shared-types").MealListResponse>(
      `/homes/${encodeURIComponent(homeId)}/meals${query ? `?${query}` : ""}`,
    );
  };
  meal = (homeId: string, mealId: string) =>
    this.request<import("@mykhaya/shared-types").Meal>(
      `/homes/${encodeURIComponent(homeId)}/meals/${encodeURIComponent(mealId)}`,
    );
  createMeal = (homeId: string, body: import("@mykhaya/shared-types").MealPayload) =>
    this.request<import("@mykhaya/shared-types").Meal>(
      `/homes/${encodeURIComponent(homeId)}/meals`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateMeal = (
    homeId: string,
    mealId: string,
    body: import("@mykhaya/shared-types").MealUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").Meal>(
      `/homes/${encodeURIComponent(homeId)}/meals/${encodeURIComponent(mealId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  setMealFavourite = (homeId: string, mealId: string, isFavourite: boolean) =>
    this.request<import("@mykhaya/shared-types").Meal>(
      `/homes/${encodeURIComponent(homeId)}/meals/${encodeURIComponent(mealId)}/favourite`,
      { method: "PATCH", body: JSON.stringify({ is_favourite: isFavourite }) },
    );
  deleteMeal = (homeId: string, mealId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/meals/${encodeURIComponent(mealId)}`,
      { method: "DELETE" },
    );
  createMealPlanEntry = (
    homeId: string,
    body: import("@mykhaya/shared-types").MealPlanEntryPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").MealPlanEntry>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/entries`,
      { method: "POST", body: JSON.stringify(body) },
    );
  mealPlanEntry = (homeId: string, entryId: string) =>
    this.request<import("@mykhaya/shared-types").MealPlanEntry>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/entries/${encodeURIComponent(entryId)}`,
    );
  updateMealPlanEntry = (
    homeId: string,
    entryId: string,
    body: import("@mykhaya/shared-types").MealPlanEntryUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").MealPlanEntry>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/entries/${encodeURIComponent(entryId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteMealPlanEntry = (homeId: string, entryId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/entries/${encodeURIComponent(entryId)}`,
      { method: "DELETE" },
    );
  mealPlanDay = (homeId: string, date: string) =>
    this.request<import("@mykhaya/shared-types").MealPlanDay>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/day?date=${encodeURIComponent(date)}`,
    );
  mealPlanWeek = (homeId: string, startDate: string) =>
    this.request<import("@mykhaya/shared-types").MealPlanWeek>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/week?start_date=${encodeURIComponent(startDate)}`,
    );
  recentMeals = (homeId: string, limit?: number) =>
    this.request<import("@mykhaya/shared-types").RecentMealsResponse>(
      `/homes/${encodeURIComponent(homeId)}/meals/recent${limit ? `?limit=${limit}` : ""}`,
    );
  saveMealPlanEntryAsMeal = (homeId: string, entryId: string) =>
    this.request<import("@mykhaya/shared-types").MealPlanEntry>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/entries/${encodeURIComponent(entryId)}/save-as-meal`,
      { method: "POST" },
    );
  addIngredientsToList = (
    homeId: string,
    mealId: string,
    body: import("@mykhaya/shared-types").AddIngredientsToListPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").AddIngredientsToListResult>(
      `/homes/${encodeURIComponent(homeId)}/meals/${encodeURIComponent(mealId)}/add-ingredients-to-list`,
      { method: "POST", body: JSON.stringify(body) },
    );
  copyMealPlanWeek = (homeId: string, body: import("@mykhaya/shared-types").CopyWeekPayload) =>
    this.request<import("@mykhaya/shared-types").CopyWeekResult>(
      `/homes/${encodeURIComponent(homeId)}/meal-plan/week/copy`,
      { method: "POST", body: JSON.stringify(body) },
    );
  // --- Household Lists -----------------------------------------------------
  lists = (homeId: string, params?: { q?: string; scope?: import("@mykhaya/shared-types").ListTemplateScope }) => {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.scope) query.set("scope", params.scope);
    const search = query.toString() ? `?${query.toString()}` : "";
    return this.request<import("@mykhaya/shared-types").HouseholdListListResponse>(
      `/homes/${encodeURIComponent(homeId)}/lists${search}`,
    );
  };
  listTemplates = (homeId: string, params?: { q?: string }) => {
    const search = params?.q ? `?q=${encodeURIComponent(params.q)}` : "";
    return this.request<import("@mykhaya/shared-types").ListTemplateListResponse>(
      `/homes/${encodeURIComponent(homeId)}/list-templates${search}`,
    );
  };
  listTemplate = (homeId: string, templateId: string) =>
    this.request<import("@mykhaya/shared-types").ListTemplate>(
      `/homes/${encodeURIComponent(homeId)}/list-templates/${encodeURIComponent(templateId)}`,
    );
  createListTemplate = (homeId: string, body: import("@mykhaya/shared-types").ListTemplateCreatePayload) =>
    this.request<import("@mykhaya/shared-types").ListTemplate>(
      `/homes/${encodeURIComponent(homeId)}/list-templates`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateListTemplate = (homeId: string, templateId: string, body: import("@mykhaya/shared-types").ListTemplateUpdatePayload) =>
    this.request<import("@mykhaya/shared-types").ListTemplate>(
      `/homes/${encodeURIComponent(homeId)}/list-templates/${encodeURIComponent(templateId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  duplicateListTemplate = (homeId: string, templateId: string, body: import("@mykhaya/shared-types").ListTemplateCreatePayload) =>
    this.request<import("@mykhaya/shared-types").ListTemplate>(
      `/homes/${encodeURIComponent(homeId)}/list-templates/${encodeURIComponent(templateId)}/duplicate`,
      { method: "POST", body: JSON.stringify(body) },
    );
  archiveListTemplate = (homeId: string, templateId: string) =>
    this.request<void>(`/homes/${encodeURIComponent(homeId)}/list-templates/${encodeURIComponent(templateId)}`, {
      method: "DELETE",
    });
  list = (homeId: string, listId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}`,
    );
  createList = (homeId: string, body: import("@mykhaya/shared-types").ListCreatePayload) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists`,
      { method: "POST", body: JSON.stringify(body) },
    );
  renameList = (
    homeId: string,
    listId: string,
    body: import("@mykhaya/shared-types").ListRenamePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteList = (homeId: string, listId: string) =>
    this.request<void>(`/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}`, {
      method: "DELETE",
    });
  addListItem = (
    homeId: string,
    listId: string,
    body: import("@mykhaya/shared-types").ListItemInputPayload,
  ) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/items`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateListItem = (
    homeId: string,
    listId: string,
    itemId: string,
    body: import("@mykhaya/shared-types").ListItemUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(itemId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  moveListScope = (
    homeId: string,
    listId: string,
    body: { scope: import("@mykhaya/shared-types").ListTemplateScope; expected_updated_at: string },
  ) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/scope`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  addListSection = (homeId: string, listId: string, name: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/sections`,
      { method: "POST", body: JSON.stringify({ name }) },
    );
  renameListSection = (homeId: string, listId: string, sectionId: string, body: { name: string; expected_updated_at: string }) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/sections/${encodeURIComponent(sectionId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  removeListSection = (homeId: string, listId: string, sectionId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/sections/${encodeURIComponent(sectionId)}`,
      { method: "DELETE" },
    );
  reorderListSections = (homeId: string, listId: string, sectionIds: string[]) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/sections/reorder`,
      { method: "POST", body: JSON.stringify({ section_ids: sectionIds }) },
    );
  removeListItem = (homeId: string, listId: string, itemId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(itemId)}`,
      { method: "DELETE" },
    );
  reorderListItems = (homeId: string, listId: string, itemIds: string[]) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/items/reorder`,
      { method: "POST", body: JSON.stringify({ item_ids: itemIds }) },
    );
  clearCompletedListItems = (homeId: string, listId: string) =>
    this.request<import("@mykhaya/shared-types").HouseholdListDetail>(
      `/homes/${encodeURIComponent(homeId)}/lists/${encodeURIComponent(listId)}/items/clear-completed`,
      { method: "POST" },
    );
  // --- Wishlists (Family-only) ---------------------------------------------
  wishlists = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").WishlistListResponse>(
      `/homes/${encodeURIComponent(homeId)}/wishlists`,
    );
  createWishlist = (
    homeId: string,
    body: import("@mykhaya/shared-types").WishlistCreatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists`,
      { method: "POST", body: JSON.stringify(body) },
    );
  wishlist = (
    homeId: string,
    wishlistId: string,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}`,
    );
  updateWishlist = (
    homeId: string,
    wishlistId: string,
    body: import("@mykhaya/shared-types").WishlistUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  deleteWishlist = (homeId: string, wishlistId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}`,
      { method: "DELETE" },
    );
  setWishlistHomeVisibility = (
    homeId: string,
    wishlistId: string,
    body: import("@mykhaya/shared-types").WishlistVisibilityUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/home-visibility`,
      { method: "POST", body: JSON.stringify(body) },
    );
  wishlistLinkPreview = (homeId: string, url: string) =>
    this.request<import("@mykhaya/shared-types").WishlistLinkPreview>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/link-preview`,
      { method: "POST", body: JSON.stringify({ url }) },
    );
  addWishlistItem = (
    homeId: string,
    wishlistId: string,
    body: import("@mykhaya/shared-types").WishlistItemCreatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/items`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateWishlistItem = (
    homeId: string,
    wishlistId: string,
    itemId: string,
    body: import("@mykhaya/shared-types").WishlistItemUpdatePayload,
  ) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(itemId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  removeWishlistItem = (homeId: string, wishlistId: string, itemId: string) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(itemId)}`,
      { method: "DELETE" },
    );
  reorderWishlistItems = (homeId: string, wishlistId: string, itemIds: string[]) =>
    this.request<import("@mykhaya/shared-types").WishlistOwnerDetail>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/items/reorder`,
      { method: "POST", body: JSON.stringify({ item_ids: itemIds }) },
    );
  lookupShareRecipient = (homeId: string, wishlistId: string, email: string) =>
    this.request<import("@mykhaya/shared-types").ShareRecipientLookupResponse>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/shares/lookup`,
      { method: "POST", body: JSON.stringify({ email }) },
    );
  createShare = (
    homeId: string,
    wishlistId: string,
    body: import("@mykhaya/shared-types").ShareCreatePayload,
  ) =>
    this.request<
      | import("@mykhaya/shared-types").ShareResponse
      | import("@mykhaya/shared-types").GuestShareCreateResponse
    >(`/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/shares`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  shares = (homeId: string, wishlistId: string) =>
    this.request<import("@mykhaya/shared-types").ShareListResponse>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/shares`,
    );
  revokeShare = (homeId: string, wishlistId: string, shareId: string) =>
    this.request<void>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/shares/${encodeURIComponent(shareId)}/revoke`,
      { method: "POST" },
    );
  regenerateGuestShare = (homeId: string, wishlistId: string, shareId: string) =>
    this.request<import("@mykhaya/shared-types").GuestShareCreateResponse>(
      `/homes/${encodeURIComponent(homeId)}/wishlists/${encodeURIComponent(wishlistId)}/shares/${encodeURIComponent(shareId)}/regenerate-guest-pin`,
      { method: "POST" },
    );
  sharedWithMe = () =>
    this.request<import("@mykhaya/shared-types").WishlistListResponse>("/wishlists/shared-with-me");
  wishlistTopLevel = (wishlistId: string) =>
    this.request<import("@mykhaya/shared-types").WishlistDetail>(
      `/wishlists/${encodeURIComponent(wishlistId)}`,
    );
  reserveWishlistItem = (wishlistId: string, itemId: string, buyerDisplayName?: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(itemId)}/reserve`,
      { method: "POST", body: JSON.stringify({ buyer_display_name: buyerDisplayName ?? null }) },
    );
  markWishlistItemBought = (wishlistId: string, itemId: string, buyerDisplayName?: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(itemId)}/mark-bought`,
      { method: "POST", body: JSON.stringify({ buyer_display_name: buyerDisplayName ?? null }) },
    );
  releaseWishlistItem = (wishlistId: string, itemId: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(itemId)}/release`,
      { method: "POST" },
    );
  // --- Wishlists: guest flow (link + PIN, separate cookie session) --------
  verifyGuestShare = (token: string, pin: string) =>
    this.request<import("@mykhaya/shared-types").GuestVerifyResponse>(
      `/wishlist/share/${encodeURIComponent(token)}/verify`,
      { method: "POST", body: JSON.stringify({ pin }) },
    );
  guestLogout = () => this.request<void>("/wishlist/guest/logout", { method: "POST" });
  guestWishlist = () =>
    this.request<import("@mykhaya/shared-types").WishlistViewerDetail>("/wishlist/guest/wishlist");
  guestReserveItem = (itemId: string, buyerDisplayName?: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlist/guest/items/${encodeURIComponent(itemId)}/reserve`,
      { method: "POST", body: JSON.stringify({ buyer_display_name: buyerDisplayName ?? null }) },
    );
  guestMarkItemBought = (itemId: string, buyerDisplayName?: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlist/guest/items/${encodeURIComponent(itemId)}/mark-bought`,
      { method: "POST", body: JSON.stringify({ buyer_display_name: buyerDisplayName ?? null }) },
    );
  guestReleaseItem = (itemId: string) =>
    this.request<import("@mykhaya/shared-types").WishlistItemViewer>(
      `/wishlist/guest/items/${encodeURIComponent(itemId)}/release`,
      { method: "POST" },
    );
  billingStatus = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").BillingStatus>(
      `/groups/${encodeURIComponent(homeId)}/billing`,
    );
  familyPricing = () =>
    this.request<import("@mykhaya/shared-types").FamilyPricing>("/billing/pricing");
  planComparison = () =>
    this.request<import("@mykhaya/shared-types").PlanComparison>("/billing/plans");
  createCheckoutSession = (
    homeId: string,
    interval: import("@mykhaya/shared-types").BillingInterval,
  ) =>
    this.request<{ checkout_url: string }>(
      `/groups/${encodeURIComponent(homeId)}/billing/checkout-session`,
      { method: "POST", body: JSON.stringify({ interval }) },
    );
  confirmCheckoutSession = (sessionId: string) =>
    this.request<{
      confirmed: boolean;
      effective_plan: string;
      subscription_status: string;
    }>("/billing/stripe/confirm-checkout", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  createPortalSession = (homeId: string) =>
    this.request<{ portal_url: string }>(
      `/groups/${encodeURIComponent(homeId)}/billing/portal-session`,
      { method: "POST" },
    );
  post = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  get = <T>(path: string) => this.request<T>(path);
  patch = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  put = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  delete = (path: string) => this.request<void>(path, { method: "DELETE" });
}

export const api = new MyKhayaClient();

export { platformApi, PlatformClient } from "./platform";

// Native (bearer-transport, ADR 0010) client — kept as separate exports
// rather than folded into MyKhayaClient, so nothing about the browser
// client's cookie/CSRF/relative-path behaviour above this line is affected
// by, or has to account for, native transport at all.
export { NativeMyKhayaClient } from "./native-client";
export type {
  NativeSession,
  NativeSessionStore,
} from "./native-session-store";
export { InMemoryNativeSessionStore } from "./native-session-store";
export {
  NATIVE_API_ORIGINS,
  nativeApiBaseUrl,
  nativeApiBaseUrlForWebHost,
} from "./native-config";
export type { NativeApiEnvironment } from "./native-config";
