// @vitest-environment jsdom
// The rest of this package runs under the default "node" environment (see
// vitest.config.ts) — only this file needs `document`/cookies, to exercise
// MyKhayaClient's real browser behaviour.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MyKhayaClient } from "./index";

// Regression coverage for the browser client's existing behaviour — added
// alongside the new native transport (native-client.ts) specifically to
// prove that behaviour is unchanged: MyKhayaClient itself was not modified
// as part of adding native support (see index.ts's comment above the
// native exports).

function jsonResponse(status: number, body: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("MyKhayaClient — browser transport", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "mk_csrf=csrf-value; path=/";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "mk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("requests a relative /api/v1 path, never an absolute origin", async () => {
    const client = new MyKhayaClient();
    await client.homes();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/groups", expect.anything());
  });

  it("always sends credentials: include", async () => {
    const client = new MyKhayaClient();
    await client.homes();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
  });

  it("attaches the X-CSRF-Token header (read from the mk_csrf cookie) on a mutating request", async () => {
    const client = new MyKhayaClient();
    await client.post("/groups", { name: "Home" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("does not attach a CSRF header on a GET request", async () => {
    const client = new MyKhayaClient();
    await client.homes();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has("X-CSRF-Token")).toBe(false);
  });

  it("never sends an Authorization header", async () => {
    const client = new MyKhayaClient();
    await client.post("/groups", { name: "Home" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has("Authorization")).toBe(false);
  });
});
