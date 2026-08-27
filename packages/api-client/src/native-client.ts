import type { User } from "@mykhaya/shared-types";
import { ApiError, parseApiResponse } from "./errors";
import type { NativeSessionStore } from "./native-session-store";

/**
 * The native (bearer-transport, ADR 0010) counterpart to `MyKhayaClient`.
 * Deliberately a separate class in the same package, not a mode flag on
 * `MyKhayaClient` — the two transports must never share a request path:
 * browser mode's relative `/api/v1` + `credentials:"include"` + CSRF-cookie
 * behaviour is untouched by this file, and this class never reads
 * `document.cookie`, never sends `credentials:"include"`, and never
 * attaches a CSRF header. See docs/architecture/adr/0010-mobile-bearer-session-tokens.md.
 *
 * The bearer token itself only ever exists in memory here, in the
 * `NativeSessionStore`, and as one outgoing `Authorization` header value —
 * it is never interpolated into a thrown error's message, a log line, or a
 * URL, and this class performs no logging of its own.
 */
export class NativeMyKhayaClient {
  constructor(
    private readonly baseUrl: string,
    private readonly store: NativeSessionStore,
    private readonly options: {
      fetch?: typeof fetch;
      /** Optional ADR 0010 "session metadata" headers — display/diagnostic
       * only on the server, never a trust input. Supplying them here means
       * a future native shell sets them once, not per call site. */
      clientHeaders?: { client?: string; platform?: string; appVersion?: string };
    } = {},
  ) {
    if (!/^https?:\/\//.test(baseUrl)) {
      throw new Error(
        "NativeMyKhayaClient requires an absolute http(s) base URL (e.g. https://api.dev.mykhaya.app/api/v1) — see packages/api-client/src/native-config.ts.",
      );
    }
  }

  private get fetchImpl(): typeof fetch {
    return this.options.fetch ?? fetch;
  }

  private baseHeaders(): Headers {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    const { client, platform, appVersion } = this.options.clientHeaders ?? {};
    if (client) headers.set("X-MyKhaya-Client", client);
    if (platform) headers.set("X-MyKhaya-Platform", platform);
    if (appVersion) headers.set("X-MyKhaya-App-Version", appVersion);
    return headers;
  }

  private async postUnauthenticated<T>(path: string, body: unknown): Promise<T> {
    const headers = this.baseHeaders();
    headers.set("Content-Type", "application/json");
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return parseApiResponse<T>(response);
  }

  /** Adult sign-in — native equivalent of the browser's POST /auth/login,
   * wired to POST /auth/mobile/login instead. Stores the returned session
   * token via the configured NativeSessionStore and returns everything the
   * response carries *except* the token, so callers never need to (and
   * cannot accidentally) handle the raw token themselves. */
  async login(email: string, password: string): Promise<User> {
    const result = await this.postUnauthenticated<User & { session_token: string }>(
      "/auth/mobile/login",
      { email, password },
    );
    const { session_token, ...user } = result;
    await this.store.set({ token: session_token });
    return user;
  }

  /** Managed-child sign-in — native equivalent of POST /auth/child/login,
   * wired to POST /auth/mobile/child/login. Same session mechanism as adult
   * login (a Session row with kind=managed_child); no separate child auth
   * architecture exists here or on the backend — see ADR 0010. */
  async childLogin(homeCode: string, username: string, pin: string): Promise<User> {
    const result = await this.postUnauthenticated<User & { session_token: string }>(
      "/auth/mobile/child/login",
      { home_code: homeCode, username, pin },
    );
    const { session_token, ...user } = result;
    await this.store.set({ token: session_token });
    return user;
  }

  /**
   * Explicit, deliberate rotation (POST /auth/mobile/sessions/rotate) — not
   * triggered automatically by `request()`. Per ADR 0010, the old token is
   * revoked server-side in the same transaction that issues the new one;
   * persisting the new token here is what "retires" the old one locally
   * (the store holds exactly one current session, so `set()` replacing it
   * *is* retiring the previous value — there is no separate delete step,
   * and no window where the app could act on both simultaneously).
   */
  async rotate(): Promise<void> {
    const current = await this.store.get();
    if (!current) {
      throw new Error("Cannot rotate: no native session is currently stored.");
    }
    const headers = this.baseHeaders();
    headers.set("Authorization", `Bearer ${current.token}`);
    const response = await this.fetchImpl(`${this.baseUrl}/auth/mobile/sessions/rotate`, {
      method: "POST",
      headers,
      cache: "no-store",
    });
    const result = await parseApiResponse<{ session_token: string }>(response);
    await this.store.set({ token: result.session_token });
  }

  /**
   * Always clears the locally stored session, whether or not the network
   * call succeeds. Per ADR 0010: blocking local logout on a successful
   * network round trip would trap a signed-in user in a household's data
   * because their device happens to be offline — a worse outcome than the
   * documented residual risk (the server-side session simply expires on its
   * own, or can be revoked from another signed-in device via
   * DELETE /auth/sessions/{id}).
   */
  async logout(): Promise<void> {
    const current = await this.store.get();
    if (current) {
      try {
        const headers = this.baseHeaders();
        headers.set("Authorization", `Bearer ${current.token}`);
        await this.fetchImpl(`${this.baseUrl}/auth/mobile/logout`, {
          method: "POST",
          headers,
          cache: "no-store",
        });
      } catch {
        // Deliberately swallowed — local logout still completes, per the
        // documented policy above.
      }
    }
    await this.store.clear();
  }

  /**
   * The single native request path. Every native feature call should go
   * through this rather than reimplementing bearer-header attachment or
   * 401 handling itself.
   */
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const current = await this.store.get();
    if (!current) {
      throw new ApiError(401, "Not signed in.");
    }
    const headers = this.baseHeaders();
    if (init.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    headers.set("Authorization", `Bearer ${current.token}`);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
    if (response.status === 401) {
      // Compare-and-clear (ADR 0010): only clear the store if this exact
      // token is still the one currently held. A concurrent rotate() may
      // already have replaced it with a newer, valid token, in which case
      // this stale failure must not touch it.
      await this.store.clearIfMatches(current.token);
    }
    return parseApiResponse<T>(response);
  }

  /**
   * Passkeys are not implemented over the native transport in this phase —
   * WebAuthn's origin/RP-ID checks and Associated Domains configuration are
   * separate future work (see the iOS/Capacitor readiness audit). This is a
   * capability report for UI gating, not a partial implementation: it must
   * stay `false` until that work is actually done, not be worked around.
   */
  passkeysSupported(): boolean {
    return false;
  }
}
