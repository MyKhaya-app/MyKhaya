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
    if (init.body) headers.set("Content-Type", "application/json");
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
  homes = () => this.request<Home[]>("/groups");
  members = (homeId: string) =>
    this.request<Member[]>(`/groups/${encodeURIComponent(homeId)}/members`);
  homeSummary = (homeId: string) =>
    this.request<import("@mykhaya/shared-types").HomeSummary>(
      `/homes/${encodeURIComponent(homeId)}/summary`,
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
  createEvent = (homeId: string, body: import("@mykhaya/shared-types").EventPayload) =>
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
    this.post<import("@mykhaya/shared-types").InvitationResponse>("/invitations/resend", {
      invitation_id: invitationId,
    });
  revokeInvitation = (invitationId: string) =>
    this.post<{ message: string }>("/invitations/revoke", {
      invitation_id: invitationId,
    });
  post = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  patch = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  delete = (path: string) => this.request<void>(path, { method: "DELETE" });
}

export const api = new MyKhayaClient();

export { platformApi, PlatformClient } from "./platform";
