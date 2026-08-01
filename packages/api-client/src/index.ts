import type {
  Home,
  HomeFeaturesEnvelope,
  Member,
  User,
} from "@mykhaya/shared-types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

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
  homeFeatures = (homeId: string) =>
    this.request<HomeFeaturesEnvelope>(
      `/homes/${encodeURIComponent(homeId)}/features`,
    );
  members = (homeId: string) =>
    this.request<Member[]>(`/groups/${encodeURIComponent(homeId)}/members`);
  post = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  patch = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  delete = (path: string) => this.request<void>(path, { method: "DELETE" });
}

export const api = new MyKhayaClient();
