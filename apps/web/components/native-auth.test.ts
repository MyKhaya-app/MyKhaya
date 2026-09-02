// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

const bootstrapSession = vi.fn();
const login = vi.fn();
const childLogin = vi.fn();
const logout = vi.fn();
const nativeClientCtor = vi.fn();

vi.mock("@mykhaya/api-client", () => ({
  api: { setRequestTransport: vi.fn() },
  InMemoryNativeSessionStore: vi.fn().mockImplementation(function InMemoryNativeSessionStore() {
    return { kind: "in-memory" };
  }),
  NativeMyKhayaClient: vi.fn().mockImplementation((...args: unknown[]) => {
    nativeClientCtor(...args);
    return { bootstrapSession, hasStoredSession: vi.fn().mockResolvedValue(true), login, childLogin, logout, request: vi.fn() };
  }),
  nativeApiBaseUrlForWebHost: vi.fn().mockReturnValue("https://api.dev.mykhaya.app/api/v1"),
}));

let nativeShell = false;
let platform: "ios" | "android" | "web" = "web";
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
  nativePlatform: () => platform,
}));

vi.mock("./keychain-native-session-store", () => ({
  KeychainNativeSessionStore: vi.fn().mockImplementation(function KeychainNativeSessionStore() {
    return { kind: "keychain" };
  }),
}));

const setBiometricSignInEnabled = vi.fn<(enabled: boolean) => Promise<void>>(async () => {});
const isBiometricSignInEnabled = vi.fn<() => Promise<boolean>>(async () => false);
const authenticateWithBiometrics = vi.fn<(reason: string) => Promise<{ ok: boolean; code?: string; message?: string }>>(async () => ({ ok: true }));
const getBiometricCapability = vi.fn(async () => ({ available: true, kind: "faceId" }));
const isBiometricCancellation = vi.fn<(result: unknown) => boolean>(() => false);
vi.mock("./native-biometric-preference", () => ({
  setBiometricSignInEnabled: (enabled: boolean) => setBiometricSignInEnabled(enabled),
  isBiometricSignInEnabled: () => isBiometricSignInEnabled(),
}));
vi.mock("./native-biometric", () => ({
  authenticateWithBiometrics: (reason: string) => authenticateWithBiometrics(reason),
  getBiometricCapability: () => getBiometricCapability(),
  isBiometricCancellation: (result: unknown) => isBiometricCancellation(result),
}));

describe("native-auth", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    nativeShell = false;
    platform = "web";
    isBiometricSignInEnabled.mockResolvedValue(false);
    authenticateWithBiometrics.mockResolvedValue({ ok: true });
    getBiometricCapability.mockResolvedValue({ available: true, kind: "faceId" });
  });

  it("bootstrapNativeSession delegates to the client's bootstrapSession", async () => {
    bootstrapSession.mockResolvedValue({ id: "u1" });
    const { bootstrapNativeSession } = await import("./native-auth");

    const user = await bootstrapNativeSession();

    expect(user).toEqual({ id: "u1" });
    expect(bootstrapSession).toHaveBeenCalledTimes(1);
  });

  it("nativeLogin delegates to the client's login", async () => {
    login.mockResolvedValue({ id: "u1" });
    const { nativeLogin } = await import("./native-auth");

    await nativeLogin("a@example.com", "pw");

    expect(login).toHaveBeenCalledWith("a@example.com", "pw");
  });

  it("requires biometric unlock before restoring an enabled native session", async () => {
    nativeShell = true;
    isBiometricSignInEnabled.mockResolvedValue(true);
    const { bootstrapNativeSession } = await import("./native-auth");

    await bootstrapNativeSession();

    expect(authenticateWithBiometrics).toHaveBeenCalledWith("Unlock MyKhaya");
    expect(bootstrapSession).toHaveBeenCalledTimes(1);
  });

  it("does not read/restore the session when biometric unlock is cancelled", async () => {
    nativeShell = true;
    isBiometricSignInEnabled.mockResolvedValue(true);
    authenticateWithBiometrics.mockResolvedValue({ ok: false, code: "userCancel", message: "cancelled" });
    isBiometricCancellation.mockReturnValue(true);
    const { bootstrapNativeSession, NativeBiometricUnlockError } = await import("./native-auth");

    await expect(bootstrapNativeSession()).rejects.toBeInstanceOf(NativeBiometricUnlockError);
    expect(bootstrapSession).not.toHaveBeenCalled();
  });

  it("nativeChildLogin delegates to the client's childLogin", async () => {
    childLogin.mockResolvedValue({ id: "c1" });
    const { nativeChildLogin } = await import("./native-auth");

    await nativeChildLogin("ABC123", "kiddo", "4242");

    expect(childLogin).toHaveBeenCalledWith("ABC123", "kiddo", "4242");
  });

  it("nativeLogout delegates to the client's logout and clears the biometric preference", async () => {
    const { nativeLogout } = await import("./native-auth");

    await nativeLogout();

    expect(logout).toHaveBeenCalledTimes(1);
    expect(setBiometricSignInEnabled).toHaveBeenCalledWith(false);
  });

  it("reuses the same client instance across calls", async () => {
    const { NativeMyKhayaClient } = await import("@mykhaya/api-client");
    const { bootstrapNativeSession, nativeLogout } = await import("./native-auth");

    await bootstrapNativeSession();
    await nativeLogout();

    expect(vi.mocked(NativeMyKhayaClient)).toHaveBeenCalledTimes(1);
  });

  it("uses the Keychain-backed store inside the native shell", async () => {
    nativeShell = true;
    const { bootstrapNativeSession } = await import("./native-auth");

    await bootstrapNativeSession();

    expect(nativeClientCtor).toHaveBeenCalledWith(
      "https://api.dev.mykhaya.app/api/v1",
      { kind: "keychain" },
      expect.anything(),
    );
  });

  it("uses the in-memory store outside the native shell", async () => {
    nativeShell = false;
    const { bootstrapNativeSession } = await import("./native-auth");

    await bootstrapNativeSession();

    expect(nativeClientCtor).toHaveBeenCalledWith(
      "https://api.dev.mykhaya.app/api/v1",
      { kind: "in-memory" },
      expect.anything(),
    );
  });
});

describe("native-auth — device identification headers", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    nativeShell = false;
    platform = "web";
  });

  it("sends iOS client/platform headers so signed-in devices show as iOS, not a raw user agent", async () => {
    platform = "ios";
    const { bootstrapNativeSession } = await import("./native-auth");

    await bootstrapNativeSession();

    expect(nativeClientCtor).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      { clientHeaders: { client: "MyKhaya iOS", platform: "iOS" } },
    );
  });

  it("sends no client headers outside the native shell — device_platform's own server-side default (Web/PWA) applies", async () => {
    platform = "web";
    const { bootstrapNativeSession } = await import("./native-auth");

    await bootstrapNativeSession();

    expect(nativeClientCtor).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      { clientHeaders: undefined },
    );
  });
});

describe("native-auth — nativeRenewSession", () => {
  const renew = vi.fn();
  afterEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    nativeShell = false;
    platform = "web";
  });

  it("delegates to the client's renew", async () => {
    renew.mockResolvedValue({ id: "u1" });
    vi.doMock("@mykhaya/api-client", () => ({
      api: { setRequestTransport: vi.fn() },
      InMemoryNativeSessionStore: vi.fn().mockImplementation(() => ({ kind: "in-memory" })),
      NativeMyKhayaClient: vi.fn().mockImplementation(() => ({
        bootstrapSession,
        login,
        childLogin,
        logout,
        renew,
        hasStoredSession: vi.fn().mockResolvedValue(true),
        request: vi.fn(),
      })),
      nativeApiBaseUrlForWebHost: vi.fn().mockReturnValue("https://api.dev.mykhaya.app/api/v1"),
    }));
    const { nativeRenewSession } = await import("./native-auth");

    const user = await nativeRenewSession();

    expect(user).toEqual({ id: "u1" });
    expect(renew).toHaveBeenCalledTimes(1);
  });
});
