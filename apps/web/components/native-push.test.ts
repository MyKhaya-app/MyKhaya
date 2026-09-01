// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
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

describe("native push platform boundary", () => {
  afterEach(() => {
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

  it("requests permission and registers the native token without PushManager", async () => {
    push.checkPermissions.mockResolvedValue({ receive: "prompt" });
    push.requestPermissions.mockResolvedValue({ receive: "granted" });
    push.register.mockImplementation(async () => {
      const registration = push.addListener.mock.calls.find(([name]) => name === "registration") as
        | [string, (token: Token) => void]
        | undefined;
      registration?.[1]({ value: "native-token" });
    });
    const { enableNativePush } = await import("./native-push");

    await expect(enableNativePush()).resolves.toEqual({ ok: true, status: "registered" });
    expect(push.requestPermissions).toHaveBeenCalledTimes(1);
    expect(push.register).toHaveBeenCalledTimes(1);
    expect(api.registerNativePushDevice).toHaveBeenCalledWith(
      expect.objectContaining({ platform: "ios", token: "native-token" }),
    );
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
});
