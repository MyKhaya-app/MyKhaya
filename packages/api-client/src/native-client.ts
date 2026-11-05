import type { User } from "@mykhaya/shared-types";
import { ApiError, parseApiResponse } from "./errors";
import type { NativeSessionStore } from "./native-session-store";

function isFormDataBody(body: BodyInit | null | undefined): boolean {
  // `instanceof FormData` is not reliable when a File/FormData comes from a
  // different WebView realm. The fetch implementation still understands the
  // standard brand and must be allowed to add the multipart boundary.
  return Boolean(body && Object.prototype.toString.call(body) === "[object FormData]");
}

/**
 * The endpoints the API serves without authentication, and the only ones the
 * native transport will call without a session. Each was checked against
 * apps/api (no user/session dependency; an anonymous request gets a normal
 * response, never a 401). Matching is exact: a literal path, or a literal
 * GET path with exactly one opaque `[A-Za-z0-9_-]` segment (URL-safe tokens
 * and legal document keys). Anything else is a protected path.
 */
const PUBLIC_GET_PATHS = new Set([
  "/config/public",
  "/public/signup-state",
  "/legal/documents",
  "/auth/providers",
]);
const PUBLIC_GET_PATH_SHAPES = [
  /^\/public\/beta\/invitations\/[A-Za-z0-9_-]{1,500}$/,
  /^\/legal\/documents\/[A-Za-z0-9_-]{1,200}$/,
];
/** Public previews that take their token as the one and only query value. */
const PUBLIC_GET_TOKEN_QUERY_PATHS = new Set(["/invitations/preview", "/calendar-shares/preview"]);
const TOKEN_QUERY = /^token=[A-Za-z0-9_-]{1,500}$/;
const PUBLIC_GET_TRANSACTION_QUERY_PATHS = new Set(["/auth/mobile/mfa/options"]);
const TRANSACTION_QUERY = /^transaction_id=[A-Za-z0-9_-]{20,256}&redemption_verifier=[A-Za-z0-9_-]{32,256}$/;
/** Public POSTs: exact paths, no query. The waitlist is rate-limited per
 * client IP server-side (enforce_rate_limit "beta-waitlist", 10/hour). */
const PUBLIC_POST_PATHS = new Set([
  "/public/beta/waitlist",
  "/auth/mobile/external/start",
  "/auth/mobile/external/browser/start",
  "/auth/mobile/external/exchange",
  "/auth/mobile/external/redeem",
  "/auth/mobile/external/recovery/register",
  "/auth/mobile/mfa/options",
  "/auth/mobile/mfa/start",
  "/auth/mobile/mfa/verify",
]);

/** Whether `path` (as passed to `request()`, relative to `/api/v1`) is an
 * allowlisted public endpoint. The path must already be canonical: dot
 * segments, empty segments, percent-encoding, backslashes or fragments make
 * it a protected path rather than being normalised into a public one. */
export function isPublicNativeEndpoint(path: string, method: string = "GET"): boolean {
  const verb = method.toUpperCase();
  if (verb !== "GET" && verb !== "POST") return false;
  const queryStart = path.indexOf("?");
  const pathname = queryStart === -1 ? path : path.slice(0, queryStart);
  const query = queryStart === -1 ? "" : path.slice(queryStart + 1);
  if (!pathname.startsWith("/") || /[%\\#]/.test(path)) return false;
  if (pathname.slice(1).split("/").some((segment) => segment === "" || segment === "." || segment === "..")) {
    return false;
  }
  if (new URL(pathname, "https://canonical.invalid").pathname !== pathname) return false;
  if (verb === "POST") return queryStart === -1 && PUBLIC_POST_PATHS.has(pathname);
  if (PUBLIC_GET_TOKEN_QUERY_PATHS.has(pathname)) return TOKEN_QUERY.test(query);
  if (PUBLIC_GET_TRANSACTION_QUERY_PATHS.has(pathname)) return TRANSACTION_QUERY.test(query);
  if (queryStart !== -1) return false;
  return PUBLIC_GET_PATHS.has(pathname) || PUBLIC_GET_PATH_SHAPES.some((shape) => shape.test(pathname));
}

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
  private readonly linkTransactions = new Set<string>();
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
    // Calling `this.fetchImpl(...)` gives the returned function the client
    // instance as `this`. WKWebView's Window.fetch rejects that receiver with
    // "Can only call Window.fetch on instances of Window". Bind both the
    // injected test implementation and the real global implementation at the
    // boundary; in a browser globalThis is the Window instance.
    return (this.options.fetch ?? globalThis.fetch).bind(globalThis);
  }

  /** Metadata-only presence check used by the native startup gate. The
   * credential value never leaves the store and is never returned. */
  async hasStoredSession(): Promise<boolean> {
    return (await this.store.get()) !== null;
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
      requestOrigin: typeof location === "undefined" ? "unknown" : location.origin,
      hasClientHeader: Boolean(this.options.clientHeaders?.client),
      hasPlatformHeader: Boolean(this.options.clientHeaders?.platform),
      hasContentType: path.includes("/login") || path.includes("/renew"),
      ...fields,
    });
  }

  /**
   * DEV-only transport probe. It sends no credentials and deliberately never
   * touches an authentication endpoint: login is rate-limited per client IP, so
   * probing /auth/mobile/login (as an earlier version did, four POSTs per
   * sign-in) burns the user's own allowance and produces 429s. It only issues
   * GETs to the public config endpoint, progressively adding the native
   * headers, and returns metadata only.
   */
  async diagnosticProbe(): Promise<string[]> {
    const results: string[] = [];
    const client = this.options.clientHeaders?.client ?? "";
    const platform = this.options.clientHeaders?.platform ?? "";
    const attempts: Array<{ label: string; headers: Record<string, string> }> = [
      { label: "GET base", headers: { Accept: "application/json" } },
      { label: "GET + client", headers: { Accept: "application/json", "X-MyKhaya-Client": client } },
      {
        label: "GET + platform",
        headers: {
          Accept: "application/json",
          "X-MyKhaya-Client": client,
          "X-MyKhaya-Platform": platform,
        },
      },
      {
        label: "GET + app-version",
        headers: {
          Accept: "application/json",
          "X-MyKhaya-Client": client,
          "X-MyKhaya-Platform": platform,
          "X-MyKhaya-App-Version": this.options.clientHeaders?.appVersion ?? "diagnostic",
        },
      },
    ];
    const path = "/config/public";
    for (const { label, headers: rawHeaders } of attempts) {
      const headers = new Headers(rawHeaders);
      for (const [key, value] of [...headers.entries()]) {
        if (!value) headers.delete(key);
      }
      try {
        const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method: "GET",
          headers,
          cache: "no-store",
        });
        results.push(`${label}: status ${response.status}`);
        this.diagnostic(path, {
          method: "GET",
          status: response.status,
          responseType: response.headers.get("content-type")?.split(";", 1)[0] ?? "unknown",
          probe: label,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : "unknown";
        results.push(
          `${label}: ${error instanceof Error ? error.name : "fetch_failed"}${message ? ` (${message})` : ""}`,
        );
        this.diagnostic(path, {
          errorCategory: "network_or_cors",
          exceptionType: error instanceof Error ? error.name : "unknown",
          errorMessage: message,
          probe: label,
        });
      }
    }
    return results;
  }

  /** An allowlisted public request (see isPublicNativeEndpoint). Works the same
   * signed in or out: it never reads the session store, never sends a bearer
   * token or cookies, and a failure (401 included) never clears the session. */
  private async publicRequest<T>(path: string, init: RequestInit): Promise<T> {
    const headers = this.baseHeaders();
    if (init.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }
    headers.delete("Authorization");
    const method = (init.method ?? "GET").toUpperCase();
    if (method === "POST") headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        signal: init.signal,
        method,
        headers,
        ...(method === "POST" ? { body: init.body } : {}),
        credentials: "omit",
        cache: "no-store",
      });
    } catch (error) {
      this.diagnostic(path, {
        errorCategory: "network_or_cors",
        exceptionType: error instanceof Error ? error.name : "unknown",
      });
      throw error;
    }
    if (!response.ok) this.diagnostic(path, { method, status: response.status });
    return parseApiResponse<T>(response);
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

  private getUnauthenticated<T>(path: string): Promise<T> {
    return this.publicRequest<T>(path, { method: "GET" });
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

  async startExternal(
    provider: "apple" | "google",
    platform: "ios" | "android",
    redemptionVerifier: string,
    intent: "login" | "link" = "login",
  ): Promise<{ transaction_id: string; nonce: string; provider: "apple" | "google"; client_id: string | null }> {
    const body = { provider, platform, intent, redemption_verifier: redemptionVerifier };
    if (intent === "link") {
      return this.request<{ transaction_id: string; nonce: string; provider: "apple" | "google"; client_id: string | null }>("/auth/mobile/external/start", {
        method: "POST",
        body: JSON.stringify(body),
      }).then((result) => { this.linkTransactions.add(result.transaction_id); return result; });
    }
    return this.postUnauthenticated("/auth/mobile/external/start", body);
  }

  externalBrowserStart(provider: "apple" | "google", platform: "ios" | "android", returnUri: string, redemptionVerifier: string, intent: "login" | "link" = "login") {
    const body = { provider, platform, intent, return_uri: returnUri, redemption_verifier: redemptionVerifier };
    if (intent === "link") {
      return this.request<{ authorization_url: string; transaction_id: string }>(
        "/auth/mobile/external/browser/start",
        { method: "POST", body: JSON.stringify(body) },
      ).then((result) => { this.linkTransactions.add(result.transaction_id); return result; });
    }
    return this.postUnauthenticated<{ authorization_url: string; transaction_id: string }>(
      "/auth/mobile/external/browser/start",
      body,
    );
  }

  async externalRedeem(transactionId: string, redemptionVerifier: string) {
    const body = { transaction_id: transactionId, redemption_verifier: redemptionVerifier };
    const result = await (this.linkTransactions.has(transactionId)
      ? this.request<
          (User & { session_token?: string; device_token?: string })
          | { authentication_state: "account_choice"; transaction_id: string; provider: "apple" | "google"; provider_email: string | null; display_name: string; can_register: boolean }
          | { authentication_state: "additional_auth_required"; transaction_id: string; provider: "apple" | "google" }
          | { message: string }
        >("/auth/mobile/external/redeem", { method: "POST", body: JSON.stringify(body) })
      : this.postUnauthenticated<
      (User & { session_token?: string; device_token?: string })
      | { authentication_state: "account_choice"; transaction_id: string; provider: "apple" | "google"; provider_email: string | null; display_name: string; can_register: boolean }
      | { authentication_state: "additional_auth_required"; transaction_id: string; provider: "apple" | "google" }
      | { message: string }
    >("/auth/mobile/external/redeem", body));
    this.linkTransactions.delete(transactionId);
    if ("session_token" in result && result.session_token) {
      const { session_token, device_token, ...user } = result;
      await this.store.set({ token: session_token, deviceToken: device_token });
      return user;
    }
    return result;
  }

  async exchangeExternal(
    transactionId: string,
    identityToken: string,
    redemptionVerifier: string,
  ): Promise<
    | User
    | { authentication_state: "account_choice"; transaction_id: string; provider: "apple" | "google"; provider_email: string | null; display_name: string; can_register: boolean }
    | { authentication_state: "additional_auth_required"; transaction_id: string; provider: "apple" | "google" }
    | { message: string }
  > {
    const body = {
      transaction_id: transactionId,
      identity_token: identityToken,
      redemption_verifier: redemptionVerifier,
    };
    const result = await (this.linkTransactions.has(transactionId)
      ? this.request<{
          session_token?: string;
          device_token?: string;
          authentication_state?: "account_choice";
          transaction_id?: string;
          provider?: "apple" | "google";
          provider_email?: string | null;
          display_name?: string;
          can_register?: boolean;
          message?: string;
        }>("/auth/mobile/external/exchange", { method: "POST", body: JSON.stringify(body) })
      : this.postUnauthenticated<{
      session_token?: string;
      device_token?: string;
      authentication_state?: "account_choice";
      transaction_id?: string;
      provider?: "apple" | "google";
      provider_email?: string | null;
      display_name?: string;
      can_register?: boolean;
      message?: string;
    }>("/auth/mobile/external/exchange", body));
    this.linkTransactions.delete(transactionId);
    if (result.session_token) {
      const { session_token, device_token, ...user } = result as User & { session_token: string; device_token?: string };
      await this.store.set({ token: session_token, deviceToken: device_token });
      return user;
    }
    return result as never;
  }

  externalRecoveryLink(transactionId: string, redemptionVerifier: string): Promise<{ message: string }> {
    return this.request("/auth/mobile/external/recovery/link", {
      method: "POST",
      body: JSON.stringify({ transaction_id: transactionId, redemption_verifier: redemptionVerifier }),
    });
  }

  async externalRecoveryRegister(body: {
    transaction_id: string;
    display_name?: string;
    legal_acceptances: { document_key: string; document_version_id: string }[];
    platform: "ios" | "android";
    redemption_verifier: string;
  }): Promise<User | { authentication_state: "additional_auth_required"; transaction_id: string; provider: "apple" | "google" }> {
    const result = await this.postUnauthenticated<User & { session_token?: string; device_token?: string; authentication_state?: "additional_auth_required"; transaction_id?: string; provider?: "apple" | "google" }>(
      "/auth/mobile/external/recovery/register",
      body,
    );
    if (!result.session_token) return result as { authentication_state: "additional_auth_required"; transaction_id: string; provider: "apple" | "google" };
    const { session_token, device_token, ...user } = result as User & { session_token: string; device_token?: string };
    await this.store.set({ token: session_token, deviceToken: device_token });
    return user;
  }

  nativeMfaOptions(transactionId: string, redemptionVerifier: string) {
    return this.getUnauthenticated<{
      methods: ("totp" | "email")[];
      destination?: string;
      policy: "optional" | "required";
      enrolment_required: boolean;
      preferred_method: "totp" | "email" | null;
    }>(`/auth/mobile/mfa/options?transaction_id=${encodeURIComponent(transactionId)}&redemption_verifier=${encodeURIComponent(redemptionVerifier)}`);
  }

  nativeMfaStart(transactionId: string, method: "totp" | "email", redemptionVerifier: string) {
    return this.postUnauthenticated<{
      method: "totp" | "email";
      destination?: string;
      provisioning_uri?: string;
      manual_key?: string;
      enrolling: boolean;
    }>("/auth/mobile/mfa/start", { transaction_id: transactionId, method, redemption_verifier: redemptionVerifier });
  }

  async nativeMfaVerify(transactionId: string, method: "totp" | "email", code: string, redemptionVerifier: string): Promise<User> {
    const result = await this.postUnauthenticated<User & { session_token: string; device_token?: string }>(
      "/auth/mobile/mfa/verify",
      { transaction_id: transactionId, method, code, redemption_verifier: redemptionVerifier },
    );
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

  /** Public account creation deliberately does not require a native session.
   * This is the native equivalent of the browser's POST /auth/register; it
   * must remain on the unauthenticated transport because a new account has no
   * session yet. */
  register(body: {
    email: unknown;
    display_name: unknown;
    password: unknown;
    invitation_token?: unknown;
    legal_acceptances?: { document_key: string; document_version_id: string }[];
    platform?: "web" | "ios" | "android";
  }): Promise<{ message: string; verification_required: boolean }> {
    return this.postUnauthenticated("/auth/register", body);
  }

  /** Email verification is also intentionally public: the verification link
   * is the credential for this one-time action, not a pre-existing session. */
  verifyEmail(token: string): Promise<{ message: string }> {
    return this.postUnauthenticated("/auth/verify-email", { token });
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
    if (isPublicNativeEndpoint(path, init.method)) return this.publicRequest<T>(path, init);
    const current = await this.store.get();
    if (!current) {
      throw new ApiError(401, "Not signed in.");
    }
    const headers = this.baseHeaders();
    if (init.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }
    if (init.body && !isFormDataBody(init.body)) {
      headers.set("Content-Type", "application/json");
    }
    if (path.endsWith("/avatar") && init.method === "POST") {
      console.debug("[avatar-upload] upload-request-starting", {
        platform: this.options.clientHeaders?.platform ?? "unknown",
        bodyType: Object.prototype.toString.call(init.body),
        multipartBody: isFormDataBody(init.body),
      });
    }
    headers.set("Authorization", `Bearer ${current.token}`);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
    if (path.endsWith("/avatar") && init.method === "POST") {
      console.debug("[avatar-upload] upload-response", { status: response.status });
    }
    if (response.status === 401) {
      // Compare-and-clear (ADR 0010): only clear the store if this exact
      // token is still the one currently held. A concurrent rotate() may
      // already have replaced it with a newer, valid token, in which case
      // this stale failure must not touch it.
      await this.store.clearIfMatches(current.token);
    }
    return parseApiResponse<T>(response);
  }

  /** Fetch protected media with the same current bearer session as API JSON.
   * Direct <img> requests cannot attach Authorization in the native shell. */
  async image(path: string): Promise<Blob> {
    const current = await this.store.get();
    if (!current) throw new ApiError(401, "Not signed in.");
    const headers = this.baseHeaders();
    headers.set("Authorization", `Bearer ${current.token}`);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: "GET",
        headers,
        cache: "no-store",
      });
    } catch (error) {
      this.diagnostic(path, {
        method: "GET",
        errorCategory: "network_or_cors",
        exceptionType: error instanceof Error ? error.name : "unknown",
      });
      throw error;
    }
    this.diagnostic(path, {
      method: "GET",
      status: response.status,
      responseType: response.headers.get("content-type")?.split(";", 1)[0] ?? "unknown",
    });
    if (response.status === 401) await this.store.clearIfMatches(current.token);
    if (!response.ok) throw new ApiError(response.status, "Could not load image.");
    const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.toLowerCase();
    if (!contentType?.startsWith("image/")) {
      throw new Error("Protected media response was not an image.");
    }
    return response.blob();
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
