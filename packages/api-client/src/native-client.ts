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
        "NativeMyKhayaClient requires an absolute http(s) base URL (e.g. https://dev.mykhaya.app/api/v1) — see packages/api-client/src/native-config.ts.",
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

  private diagnostic(path: string, fields: Record<string, unknown>): void {
    // Safe native diagnostics: never include request bodies, bearer tokens,
    // cookies, or authorization headers. This is intentionally console-only
    // so a TestFlight device can expose the failing stage in Xcode logs.
    console.info("[NATIVE AUTH]", {
      native: true,
      platform: this.options.clientHeaders?.platform ?? "unknown",
      requestUrl: `${this.baseUrl}${path}`,
      ...fields,
    });
  }

  private async postUnauthenticated<T>(path: string, body: unknown): Promise<T> {
    const headers = this.baseHeaders();
    headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
      });
    } catch (error) {
      this.diagnostic(path, {
        errorCategory: "network_or_cors",
        exceptionType: error instanceof Error ? error.name : "unknown",
      });
      throw error;
    }
    this.diagnostic(path, {
      method: "POST",
      status: response.status,
      responseType: response.headers.get("content-type")?.split(";", 1)[0] ?? "unknown",
    });
    try {
      return await parseApiResponse<T>(response);
    } catch (error) {
      this.diagnostic(path, {
        errorCategory: error instanceof ApiError ? "http" : "response_parse",
        ...(error instanceof ApiError ? { errorCode: error.code, errorMessage: error.message } : {}),
      });
      throw error;
    }
  }

  /** Adult sign-in — native equivalent of the browser's POST /auth/login,
   * wired to POST /auth/mobile/login instead. Stores the returned session
   * token (and long-lived device/renewal token — see native-session-store's
   * NativeSession.deviceToken) via the configured NativeSessionStore and
   * returns everything the response carries *except* those tokens, so
   * callers never need to (and cannot accidentally) handle them
   * themselves. */
  async login(email: string, password: string): Promise<User> {
    const result = await this.postUnauthenticated<
      User & { session_token: string; device_token?: string }
    >("/auth/mobile/login", { email, password });
    const { session_token, device_token, ...user } = result;
    await this.store.set({ token: session_token, deviceToken: device_token });
    return user;
  }

  /** Managed-child sign-in — native equivalent of POST /auth/child/login,
   * wired to POST /auth/mobile/child/login. Same session mechanism as adult
   * login (a Session row with kind=managed_child); no separate child auth
   * architecture exists here or on the backend — see ADR 0010. */
  async childLogin(homeCode: string, username: string, pin: string): Promise<User> {
    const result = await this.postUnauthenticated<
      User & { session_token: string; device_token?: string }
    >("/auth/mobile/child/login", { home_code: homeCode, username, pin });
    const { session_token, device_token, ...user } = result;
    await this.store.set({ token: session_token, deviceToken: device_token });
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
    const result = await parseApiResponse<{ session_token: string; device_token?: string }>(
      response,
    );
    // Rotation never returns a new device_token (see routers.auth's
    // rotate_mobile_session) — explicitly carry the existing one forward
    // rather than relying on the store to merge it in, so this is correct
    // regardless of whether a given NativeSessionStore implementation
    // overwrites wholesale or merges (InMemoryNativeSessionStore does the
    // former).
    await this.store.set({
      token: result.session_token,
      deviceToken: result.device_token ?? current.deviceToken,
    });
  }

  /**
   * Silently mints a fresh session from the long-lived device/renewal
   * credential once the session token itself has expired — the
   * bearer-transport equivalent of the browser's silent /auth/renew (see
   * routers.auth.renew_mobile_session). Unlike `rotate()`, this does not
   * require a currently-valid session token at all, only a deviceToken; it
   * is what makes "terminate the app, reopen it days later" work without a
   * password. Throws (and leaves the store untouched) if there is no
   * deviceToken to renew from, or if the server rejects it
   * (revoked/expired/unknown) — callers should treat either as "this
   * native session cannot be silently restored," the same signed-out
   * outcome bootstrapSession() already returns for an outright-missing
   * session.
   *
   * `deviceTokenOverride`, read from the store itself when omitted, exists
   * for bootstrapSession(): a prior 401 on this same bootstrap pass may
   * already have triggered request()'s compare-and-clear, wiping the store
   * (deviceToken included) before renewal is even attempted — passing the
   * token captured *before* that happened is what lets renewal still
   * succeed in that case.
   */
  async renew(deviceTokenOverride?: string): Promise<User> {
    const deviceToken = deviceTokenOverride ?? (await this.store.get())?.deviceToken;
    if (!deviceToken) {
      throw new ApiError(401, "No renewable native session is currently stored.");
    }
    const result = await this.postUnauthenticated<
      User & { session_token: string; device_token?: string }
    >("/auth/mobile/sessions/renew", { device_token: deviceToken });
    const { session_token, device_token, ...user } = result;
    await this.store.set({ token: session_token, deviceToken: device_token ?? deviceToken });
    return user;
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
   * App-start native auth bootstrap (task: "read current token, determine
   * if a session exists, validate it against the API, recognise
   * invalid/revoked sessions, cleanly enter a signed-out state"). Returns
   * the current user if a stored token is still valid, or `null` if there
   * is no stored session at all, or the server has rejected it and it
   * couldn't be silently renewed either — in the `null` case the store has
   * already been left in a clean signed-out state (either via `request()`'s
   * compare-and-clear, or by an explicit `clear()` if renewal was attempted
   * and also failed), so the caller can treat `null` as "signed out"
   * without any further cleanup step.
   *
   * On a 401 (the session_token has expired or been revoked), this
   * attempts exactly one `renew()` using the stored deviceToken before
   * giving up — this is what lets "terminate the app, reopen it days
   * later" skip the login screen entirely, the same as a browser tab that
   * outlives its own short session cookie via the silent /auth/renew.
   * There is deliberately no retry loop beyond this single attempt: a
   * renew() failure means the device credential itself was rejected
   * (revoked/expired/unknown), which retrying cannot fix.
   *
   * Any other failure (network error, 5xx) is rethrown rather than treated
   * as signed-out, since that is a transient condition, not proof the
   * session is invalid — see Phase 12's authenticated-but-offline
   * distinction: a network error here must never clear a valid stored
   * session.
   */
  async bootstrapSession(): Promise<User | null> {
    const current = await this.store.get();
    if (!current) return null;
    try {
      return await this.request<User>("/users/me");
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
    }
    // Captured from `current` (read above, before request()'s own
    // compare-and-clear could have wiped the store) rather than re-read
    // here — see renew()'s docstring.
    if (!current.deviceToken) {
      await this.store.clear();
      return null;
    }
    try {
      return await this.renew(current.deviceToken);
    } catch (renewError) {
      if (renewError instanceof ApiError && renewError.status === 401) {
        await this.store.clear();
        return null;
      }
      throw renewError;
    }
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
