import { ApiError } from "./errors";

export class PlatformClient {
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const csrf =
      typeof document === "undefined"
        ? undefined
        : document.cookie.match(/(?:^|; )mk_admin_csrf=([^;]+)/)?.[1];
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (csrf && !["GET", "HEAD", "OPTIONS"].includes(init.method ?? "GET"))
      headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    const response = await fetch(`/api/v1/platform${path}`, {
      ...init,
      credentials: "include",
      cache: "no-store",
      headers,
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new ApiError(response.status, body?.detail ?? "The request could not be completed.");
    }
    return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
  }

  get = <T>(path: string) => this.request<T>(path);
  post = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  patch = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  put = <T>(path: string, body: unknown) =>
    this.request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  delete = <T>(path: string) => this.request<T>(path, { method: "DELETE" });
}

export const platformApi = new PlatformClient();
