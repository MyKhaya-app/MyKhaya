// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Token } from "@capacitor/push-notifications";

const push = vi.hoisted(() => ({
  checkPermissions: vi.fn(),
  requestPermissions: vi.fn(),
  register: vi.fn(),
  addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
}));
const api = vi.hoisted(() => ({
  registerNativePushDevice: vi.fn().mockResolvedValue({ id: "registration-1" }),
  deleteNativePushDevice: vi.fn().mockResolvedValue(undefined),
}));
const platform = vi.hoisted(() => ({ native: true, value: "ios" as "ios" | "web" }));

vi.mock("@capacitor/push-notifications", () => ({ PushNotifications: push }));
vi.mock("@mykhaya/api-client", () => ({ api }));
vi.mock("./native-runtime", () => ({
  isNativeShell: () => platform.native,
  nativePlatform: () => platform.value,
}));

function listenerFor<T>(event: string): (value: T) => void {
  const calls = push.addListener.mock.calls as unknown[][];
  const listener = calls.find((call) => call[0] === event)?.[1];
  if (typeof listener !== "function") throw new Error(`Missing ${event} listener`);
  return listener as (value: T) => void;
}

describe("native push platform boundary", () => {
  beforeEach(() => {
    push.checkPermissions.mockResolvedValue({ receive: "granted" });
    push.requestPermissions.mockResolvedValue({ receive: "granted" });
    push.register.mockResolvedValue(undefined);
    api.registerNativePushDevice.mockResolvedValue({ id: "registration-1" });
    api.deleteNativePushDevice.mockResolvedValue(undefined);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.resetModules();
    vi.clearAllMocks();
    platform.native = true;
    platform.value = "ios";
  });

  it("does not invoke native registration outside the native iOS shell", async () => {
    platform.native = false;
    const { enableNativePush } = await import("./native-push");

    await expect(enableNativePush()).resolves.toEqual({ ok: false, status: "unsupported" });
    expect(push.register).not.toHaveBeenCalled();
  });

  it("attaches listeners before register and registers the native token", async () => {
    push.checkPermissions.mockResolvedValue({ receive: "prompt" });
    push.requestPermissions.mockResolvedValue({ receive: "granted" });
    push.register.mockImplementation(async () => { listenerFor<Token>("registration")({ value: "native-token" }); });
    const { enableNativePush } = await import("./native-push");

    await expect(enableNativePush()).resolves.toEqual({ ok: true, status: "registered" });
    expect(push.requestPermissions).toHaveBeenCalledTimes(1);
    expect(push.register).toHaveBeenCalledTimes(1);
    const registerOrder = push.register.mock.invocationCallOrder[0];
    const listenerOrder = push.addListener.mock.invocationCallOrder.at(-1);
    expect(registerOrder).toBeDefined();
    expect(listenerOrder).toBeDefined();
    expect(registerOrder!).toBeGreaterThan(listenerOrder!);
    expect(api.registerNativePushDevice).toHaveBeenCalledWith(
      expect.objectContaining({ platform: "ios", token: "native-token" }),
    );
  });

  it("shares one registration when startup reconciliation overlaps a permission grant", async () => {
    let checks = 0;
    push.checkPermissions.mockImplementation(async () => {
      checks += 1;
      return checks === 2 ? { receive: "prompt" } : { receive: "granted" };
    });
    push.requestPermissions.mockResolvedValue({ receive: "granted" });
    push.register.mockImplementation(async () => {
      listenerFor<Token>("registration")({ value: "native-token" });
    });
    const { reconcileNativePush, requestNativePermissionOnly } = await import("./native-push");

    const startup = reconcileNativePush();
    const permission = requestNativePermissionOnly();
    await Promise.all([startup, permission]);
    await vi.waitFor(() => expect(api.registerNativePushDevice).toHaveBeenCalledTimes(1));
    expect(push.register).toHaveBeenCalledTimes(1);
  });

  it("shares one in-flight operation across concurrent registration requests", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    push.register.mockImplementation(async () => {
      await gate;
      listenerFor<Token>("registration")({ value: "native-token" });
    });
    const { enableNativePush } = await import("./native-push");

    const first = enableNativePush();
    const second = enableNativePush();
    await vi.waitFor(() => expect(push.register).toHaveBeenCalledTimes(1));
    release();
    await expect(Promise.all([first, second])).resolves.toEqual([
      { ok: true, status: "registered" },
      { ok: true, status: "registered" },
    ]);
  });

  it("reports an OS registration error and does not call the backend", async () => {
    push.register.mockImplementation(async () => {
      listenerFor<unknown>("registrationError")({ message: "registration failed" });
    });
    const { enableNativePush } = await import("./native-push");

    await expect(enableNativePush()).resolves.toEqual({ ok: false, status: "error" });
    expect(api.registerNativePushDevice).not.toHaveBeenCalled();
  });

  it("preserves an error result when backend registration fails", async () => {
    api.registerNativePushDevice.mockRejectedValueOnce(new Error("backend unavailable"));
    push.register.mockImplementation(async () => { listenerFor<Token>("registration")({ value: "native-token" }); });
    const { enableNativePush } = await import("./native-push");

    await expect(enableNativePush()).resolves.toEqual({ ok: false, status: "error" });
  });

  it("returns an error when registration times out", async () => {
    vi.useFakeTimers();
    const { enableNativePush } = await import("./native-push");
    const pending = enableNativePush();
    await vi.advanceTimersByTimeAsync(10_001);

    await expect(pending).resolves.toEqual({ ok: false, status: "error" });
  });

  it("does not remove listeners while registration is pending", async () => {
    vi.useFakeTimers();
    const removers: Array<ReturnType<typeof vi.fn>> = [];
    push.addListener.mockImplementation(async () => {
      const remove = vi.fn();
      removers.push(remove);
      return { remove };
    });
    const { cleanupNativePush, enableNativePush } = await import("./native-push");
    const pending = enableNativePush();
    await Promise.resolve();
    await Promise.resolve();
    await cleanupNativePush();
    expect(removers.every((remove) => !remove.mock.calls.length)).toBe(true);
    await vi.advanceTimersByTimeAsync(10_001);
    await expect(pending).resolves.toEqual({ ok: false, status: "error" });
    expect(removers.every((remove) => remove.mock.calls.length === 1)).toBe(true);
  });

  it("never logs the APNs token", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    push.register.mockImplementation(async () => { listenerFor<Token>("registration")({ value: "secret-apns-token" }); });
    const { enableNativePush } = await import("./native-push");

    await enableNativePush();
    expect(JSON.stringify(info.mock.calls)).not.toContain("secret-apns-token");
  });

  it("keeps notification tap destinations on the internal allowlist", async () => {
    const { safeNativePushPath } = await import("./native-push");

    expect(safeNativePushPath("/calendar/2026-09-01")).toBe("/calendar/2026-09-01");
    expect(safeNativePushPath("https://evil.example")).toBe("/home");
    expect(safeNativePushPath("//evil.example/path")).toBe("/home");
    expect(safeNativePushPath("/settings/notifications")).toBe("/settings/notifications");
    expect(safeNativePushPath("/admin/users")).toBe("/home");
  });

  it("does not duplicate listeners and can clean them up for account switching", async () => {
    const { cleanupNativePush, initializeNativePush } = await import("./native-push");

    await initializeNativePush(() => undefined);
    await initializeNativePush(() => undefined);
    expect(push.addListener).toHaveBeenCalledTimes(4);

    await cleanupNativePush();
    expect(push.addListener.mock.results.every((result) => result.value)).toBe(true);
    await initializeNativePush(() => undefined);
    expect(push.addListener).toHaveBeenCalledTimes(8);
  });

  describe("requestNativePermissionOnly — permission decoupled from registration", () => {
    it("returns 'unsupported' outside the native iOS shell", async () => {
      platform.native = false;
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("unsupported");
      expect(push.requestPermissions).not.toHaveBeenCalled();
    });

    it("returns 'denied' without calling requestPermissions() again when already denied", async () => {
      push.checkPermissions.mockResolvedValue({ receive: "denied" });
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("denied");
      expect(push.requestPermissions).not.toHaveBeenCalled();
    });

    it("returns 'granted' immediately, without waiting on backend registration, when already granted", async () => {
      push.checkPermissions.mockResolvedValue({ receive: "granted" });
      // Registration itself hangs — if requestNativePermissionOnly awaited
      // it, this test would time out instead of resolving fast.
      api.registerNativePushDevice.mockReturnValue(new Promise(() => {}));
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("granted");
    });

    it("still triggers APNs registration in the background after granting", async () => {
      push.checkPermissions.mockResolvedValueOnce({ receive: "prompt" }).mockResolvedValue({ receive: "granted" });
      push.requestPermissions.mockResolvedValue({ receive: "granted" });
      push.register.mockImplementation(async () => {
        listenerFor<Token>("registration")({ value: "native-token" });
      });
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("granted");
      await vi.waitFor(() => expect(api.registerNativePushDevice).toHaveBeenCalledTimes(1));
    });

    it("prompts exactly once when not yet requested, and maps a fresh denial to 'denied'", async () => {
      push.checkPermissions.mockResolvedValue({ receive: "prompt" });
      push.requestPermissions.mockResolvedValue({ receive: "denied" });
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("denied");
      expect(push.requestPermissions).toHaveBeenCalledTimes(1);
    });

    it("maps a dismissed prompt (still 'prompt') to 'not_requested'", async () => {
      push.checkPermissions.mockResolvedValue({ receive: "prompt" });
      push.requestPermissions.mockResolvedValue({ receive: "prompt" });
      const { requestNativePermissionOnly } = await import("./native-push");

      await expect(requestNativePermissionOnly()).resolves.toBe("not_requested");
    });
  });

  describe("nativePushDiagnostics — read-only session state for About > Diagnostics", () => {
    it("reports no token/registration before anything has registered", async () => {
      const { nativePushDiagnostics } = await import("./native-push");
      expect(nativePushDiagnostics()).toEqual({ tokenPresent: false, registered: false });
    });

    it("reports token present and registered once enableNativePush completes successfully", async () => {
      push.register.mockImplementation(async () => {
        listenerFor<Token>("registration")({ value: "native-token" });
      });
      const { enableNativePush, nativePushDiagnostics } = await import("./native-push");

      await enableNativePush();
      expect(nativePushDiagnostics()).toEqual({ tokenPresent: true, registered: true });
    });

    it("persists a last-registered-at timestamp to localStorage on successful registration", async () => {
      window.localStorage.removeItem("mykhaya.native.push.last-registered-at");
      push.register.mockImplementation(async () => {
        listenerFor<Token>("registration")({ value: "native-token" });
      });
      const { enableNativePush } = await import("./native-push");

      const before = Date.now();
      await enableNativePush();
      const stored = Number(window.localStorage.getItem("mykhaya.native.push.last-registered-at"));
      expect(stored).toBeGreaterThanOrEqual(before);
    });
  });
});
