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

describe("NativeMyKhayaClient — passkeys", () => {
  it("reports passkeys as unsupported over the native transport", () => {
    const client = new NativeMyKhayaClient(BASE_URL, new InMemoryNativeSessionStore());
    expect(client.passkeysSupported()).toBe(false);
  });
});
