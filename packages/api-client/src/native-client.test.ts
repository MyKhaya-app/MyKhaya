import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors";
import { NativeMyKhayaClient } from "./native-client";
import { InMemoryNativeSessionStore } from "./native-session-store";

const BASE_URL = "https://api.dev.mykhaya.app/api/v1";

function jsonResponse(status: number, body: unknown, extraHeaders: Record<string, string> = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...extraHeaders },
  });
}

describe("NativeMyKhayaClient — construction", () => {
  it("rejects a relative or non-http(s) base URL", () => {
    const store = new InMemoryNativeSessionStore();
    expect(() => new NativeMyKhayaClient("/api/v1", store)).toThrow(/absolute http\(s\)/);
    expect(() => new NativeMyKhayaClient("capacitor://localhost", store)).toThrow();
  });

  it("accepts a configured absolute origin", () => {
    const store = new InMemoryNativeSessionStore();
    expect(() => new NativeMyKhayaClient(BASE_URL, store)).not.toThrow();
  });
});

describe("NativeMyKhayaClient — login", () => {
  it("binds an injected Window.fetch-like implementation to globalThis", async () => {
    const receiverSensitiveFetch = vi.fn(function (this: unknown) {
      if (this !== globalThis) throw new TypeError("Can only call Window.fetch on instances of Window");
      return Promise.resolve(jsonResponse(401, { detail: "invalid" }));
    });
    const client = new NativeMyKhayaClient(
      BASE_URL,
      new InMemoryNativeSessionStore(),
      { fetch: receiverSensitiveFetch as typeof fetch },
    );

    await expect(client.login("a@example.com", "wrong")).rejects.toMatchObject({ status: 401 });
    expect(receiverSensitiveFetch).toHaveBeenCalledTimes(1);
    expect(receiverSensitiveFetch.mock.instances[0]).toBe(globalThis);
  });

  it("posts to /auth/mobile/login, stores the token, and never returns it to the caller", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "u1",
        email: "a@example.com",
        display_name: "Adult",
        email_verified: true,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "adult",
        session_token: "raw-token-value",
      }),
    );
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.login("a@example.com", "correct horse");

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/mobile/login`,
      expect.objectContaining({ method: "POST" }),
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBeUndefined();
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@example.com",
      password: "correct horse",
    });
    expect(user).not.toHaveProperty("session_token");
    expect(await store.get()).toEqual({ token: "raw-token-value" });
  });

  it("never sends credentials: include or reads document.cookie", async () => {
    const originalDocument = (globalThis as { document?: unknown }).document;
    // Proves the native client's own code never touches document.cookie —
    // if it did, this stub would throw the moment it's read.
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      get() {
        throw new Error("NativeMyKhayaClient must never read document.cookie");
      },
    });
    try {
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse(200, {
          id: "u1",
          email: null,
          display_name: "Kid",
          email_verified: false,
          birth_month: null,
          birth_day: null,
          birth_year: null,
          avatar_version: null,
          principal_type: "managed_child",
          session_token: "child-token",
        }),
      );
      const store = new InMemoryNativeSessionStore();
      const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });
      await client.childLogin("ABC123", "kiddo", "4242");
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(init.credentials).toBeUndefined();
    } finally {
      if (originalDocument === undefined) {
        delete (globalThis as { document?: unknown }).document;
      } else {
        Object.defineProperty(globalThis, "document", {
          configurable: true,
          value: originalDocument,
        });
      }
    }
  });
});

describe("NativeMyKhayaClient — DEV diagnostic probe", () => {
  it("probes GET and progressively adds native headers without logging sensitive data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "invalid" }));
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const client = new NativeMyKhayaClient(BASE_URL, new InMemoryNativeSessionStore(), {
      fetch: fetchMock,
      clientHeaders: { client: "MyKhaya iOS", platform: "iOS" },
    });

    await expect(client.diagnosticProbe()).resolves.toEqual([
      "GET base: status 401",
      "POST content-type: status 401",
      "POST + client: status 401",
      "POST + platform: status 401",
      "POST + app-version: status 401",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(5);
    const serializedLogs = JSON.stringify(info.mock.calls);
    expect(serializedLogs).not.toContain("native-diagnostic-invalid");
    expect(serializedLogs).not.toContain("password");
    info.mockRestore();
  });
});

describe("NativeMyKhayaClient — authenticated requests", () => {
  it("attaches Authorization: Bearer using the currently stored token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [] }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "stored-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.request("/groups");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer stored-token");
    expect(headers.has("X-CSRF-Token")).toBe(false);
    expect(init.credentials).toBeUndefined();
  });

  it("throws before making a request when no session is stored", async () => {
    const fetchMock = vi.fn();
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.request("/groups")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("compare-and-clear: a 401 clears the store only if the token used is still current", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Expired." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "stale-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.request("/groups")).rejects.toBeInstanceOf(ApiError);
    expect(await store.get()).toBeNull();
  });

  it("compare-and-clear: a stale 401 must not clear a token a concurrent rotation already replaced", async () => {
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    // Request A reads "token-a" as `current` at call time...
    let resolveFetch!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    const fetchMock = vi.fn().mockReturnValue(pending);
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });
    const requestA = client.request("/groups");

    // ...but a rotation completes and overwrites the store with "token-b"
    // before request A's (401) response actually arrives.
    await store.set({ token: "token-b" });
    resolveFetch(jsonResponse(401, { detail: "Expired." }));

    await expect(requestA).rejects.toBeInstanceOf(ApiError);
    expect(await store.get()).toEqual({ token: "token-b" });
  });
});

describe("NativeMyKhayaClient — rotation", () => {
  it("persists the new token, replacing the old one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { session_token: "token-b" }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.rotate();

    expect(await store.get()).toEqual({ token: "token-b" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-a");
  });

  it("throws rather than calling the network when there is no session to rotate", async () => {
    const fetchMock = vi.fn();
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });
    await expect(client.rotate()).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("carries the existing deviceToken forward even though rotate's own response never returns one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { session_token: "token-b" }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a", deviceToken: "device-a" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.rotate();

    expect(await store.get()).toEqual({ token: "token-b", deviceToken: "device-a" });
  });
});

describe("NativeMyKhayaClient — login/childLogin store the device token", () => {
  it("login stores the device_token alongside the session token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "u1",
        email: "a@example.com",
        display_name: "Adult",
        email_verified: true,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "adult",
        session_token: "raw-token-value",
        device_token: "raw-device-value",
      }),
    );
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.login("a@example.com", "correct horse");

    expect(user).not.toHaveProperty("device_token");
    expect(await store.get()).toEqual({ token: "raw-token-value", deviceToken: "raw-device-value" });
  });

  it("childLogin stores the device_token alongside the session token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "c1",
        email: null,
        display_name: "Kid",
        email_verified: false,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "managed_child",
        session_token: "child-token",
        device_token: "child-device-token",
      }),
    );
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.childLogin("ABC123", "kiddo", "4242");

    expect(await store.get()).toEqual({ token: "child-token", deviceToken: "child-device-token" });
  });
});

describe("NativeMyKhayaClient — renew", () => {
  it("posts the stored deviceToken (never the Authorization header) and persists the new tokens", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "u1",
        email: "a@example.com",
        display_name: "Adult",
        email_verified: true,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "adult",
        session_token: "new-session-token",
        device_token: "new-device-token",
      }),
    );
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "expired-token", deviceToken: "old-device-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.renew();

    expect(user.id).toBe("u1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/auth/mobile/sessions/renew`);
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
    expect(JSON.parse(init.body as string)).toEqual({ device_token: "old-device-token" });
    expect(await store.get()).toEqual({
      token: "new-session-token",
      deviceToken: "new-device-token",
    });
  });

  it("accepts an explicit deviceToken override instead of reading the store", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "u1",
        email: "a@example.com",
        display_name: "Adult",
        email_verified: true,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "adult",
        session_token: "new-session-token",
      }),
    );
    // The store is empty — the override must still be used, exactly the
    // scenario bootstrapSession() relies on after compare-and-clear has
    // already wiped the store.
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.renew("captured-device-token");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ device_token: "captured-device-token" });
  });

  it("throws without calling the network when there is no deviceToken anywhere", async () => {
    const fetchMock = vi.fn();
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "some-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.renew()).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("propagates a rejected/expired device token as an ApiError without touching the store", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Expired." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "some-token", deviceToken: "revoked-device-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.renew()).rejects.toBeInstanceOf(ApiError);
    // renew() itself never clears anything on failure — bootstrapSession()
    // (the only caller) decides what to do with a rejected renewal.
    expect(await store.get()).toEqual({ token: "some-token", deviceToken: "revoked-device-token" });
  });
});

describe("NativeMyKhayaClient — bootstrapSession renews an expired session", () => {
  function userBody(overrides: Record<string, unknown> = {}) {
    return {
      id: "u1",
      email: "a@example.com",
      display_name: "Adult",
      email_verified: true,
      birth_month: null,
      birth_day: null,
      birth_year: null,
      avatar_version: null,
      principal_type: "adult",
      ...overrides,
    };
  }

  it("falls back to renew() on a 401 and returns the user on success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Expired." })) // GET /users/me
      .mockResolvedValueOnce(
        jsonResponse(200, {
          ...userBody(),
          session_token: "renewed-session-token",
          device_token: "renewed-device-token",
        }),
      ); // POST /auth/mobile/sessions/renew
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "expired-token", deviceToken: "still-valid-device-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.bootstrapSession();

    expect(user?.id).toBe("u1");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(await store.get()).toEqual({
      token: "renewed-session-token",
      deviceToken: "renewed-device-token",
    });
  });

  it("returns null and clears the store when the device token has also been rejected", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Expired." }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Revoked." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "expired-token", deviceToken: "revoked-device-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.bootstrapSession();

    expect(user).toBeNull();
    expect(await store.get()).toBeNull();
  });

  it("returns null without attempting renewal when there was never a deviceToken", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Expired." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "expired-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.bootstrapSession();

    expect(user).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await store.get()).toBeNull();
  });

  it("still rethrows a non-401 (network/5xx) failure without attempting renewal", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "some-token", deviceToken: "some-device-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.bootstrapSession()).rejects.toThrow("network down");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // A transient network failure must never clear a valid stored session —
    // see Phase 12's authenticated-but-offline distinction.
    expect(await store.get()).toEqual({ token: "some-token", deviceToken: "some-device-token" });
  });
});

describe("NativeMyKhayaClient — logout", () => {
  it("calls /auth/mobile/logout and clears the stored token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(204, undefined));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await client.logout();

    expect(await store.get()).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/mobile/logout`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("still clears the stored token locally even when the network call fails", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.logout()).resolves.toBeUndefined();
    expect(await store.get()).toBeNull();
  });

  it("does nothing over the network when there was no session to begin with", async () => {
    const fetchMock = vi.fn();
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });
    await client.logout();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("NativeMyKhayaClient — error handling never leaks the token", () => {
  it("a thrown ApiError's message never contains the bearer token value", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(403, { detail: "You do not have permission." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "super-secret-token-value" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    try {
      await client.request("/groups");
      throw new Error("expected request() to reject");
    } catch (error) {
      expect(String((error as Error).message)).not.toContain("super-secret-token-value");
      expect(JSON.stringify(error)).not.toContain("super-secret-token-value");
    }
  });
});

describe("NativeMyKhayaClient — bootstrapSession", () => {
  it("returns null without calling the network when no session is stored", async () => {
    const fetchMock = vi.fn();
    const store = new InMemoryNativeSessionStore();
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.bootstrapSession()).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the current user when the stored token is still valid", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "u1",
        email: "a@example.com",
        display_name: "Adult",
        email_verified: true,
        birth_month: null,
        birth_day: null,
        birth_year: null,
        avatar_version: null,
        principal_type: "adult",
      }),
    );
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "valid-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    const user = await client.bootstrapSession();

    expect(user?.id).toBe("u1");
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/users/me`, expect.anything());
  });

  it("returns null and leaves the session cleared when the stored token is rejected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Expired." }));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "stale-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.bootstrapSession()).resolves.toBeNull();
    expect(await store.get()).toBeNull();
  });

  it("rethrows a non-401 failure rather than treating it as signed-out", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "valid-token" });
    const client = new NativeMyKhayaClient(BASE_URL, store, { fetch: fetchMock });

    await expect(client.bootstrapSession()).rejects.toThrow("network down");
    expect(await store.get()).toEqual({ token: "valid-token" });
  });
});

describe("NativeMyKhayaClient — passkeys", () => {
  it("reports passkeys as unsupported over the native transport", () => {
    const client = new NativeMyKhayaClient(BASE_URL, new InMemoryNativeSessionStore());
    expect(client.passkeysSupported()).toBe(false);
  });
});
