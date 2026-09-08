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
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = body?.detail;
      // The commercial-entitlement errors (e.g. require_within_limit, which
      // the "Move member" destination-limit check reuses) return a
      // structured {code, message, ...} detail rather than a plain string —
      // unwrap it the same way the consumer client's parseApiResponse does,
      // so it renders as readable text instead of "[object Object]".
      if (detail && typeof detail === "object" && "message" in detail) {
        throw new ApiError(response.status, String((detail as { message: unknown }).message));
      }
      throw new ApiError(
        response.status,
        typeof detail === "string" ? detail : "The request could not be completed.",
      );
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
  // Most DELETEs need no body; the complimentary-access revoke endpoint
  // (Phase 2) is a privileged action that requires a reason, so `body` is
  // optional rather than adding a second method.
  delete = <T>(path: string, body?: unknown) =>
    this.request<T>(path, { method: "DELETE", ...(body ? { body: JSON.stringify(body) } : {}) });
}

export const platformApi = new PlatformClient();
