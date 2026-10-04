// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

type Status = "unsupported" | "not_requested" | "granted" | "denied" | "restricted";

const adapter = vi.hoisted(() => ({
  getPermissionStatus: vi.fn<() => Promise<Status>>(),
  requestPermission: vi.fn<() => Promise<Status>>(),
  openSystemNotificationSettings: vi.fn<() => Promise<void>>(),
  refreshPermissionStatus: vi.fn<() => Promise<Status>>(),
}));
let appStateListener: ((state: { isActive: boolean }) => void) | undefined;
const appAddListener = vi.fn((event: string, listener: (state: { isActive: boolean }) => void) => {
  if (event === "appStateChange") appStateListener = listener;
  return Promise.resolve({ remove: vi.fn() });
});

vi.mock("./notification-permission", () => ({
  getNotificationPermissionAdapter: () => adapter,
}));
vi.mock("@capacitor/app", () => ({ App: { addListener: appAddListener } }));

beforeEach(() => {
  appStateListener = undefined;
  adapter.getPermissionStatus.mockReset().mockResolvedValue("not_requested");
  adapter.requestPermission.mockReset().mockResolvedValue("granted");
  adapter.openSystemNotificationSettings.mockReset().mockResolvedValue(undefined);
  adapter.refreshPermissionStatus.mockReset().mockResolvedValue("granted");
});

afterEach(() => {
  vi.resetModules();
});

describe("useNotificationPermission", () => {
  it("reads status once on mount", async () => {
    const { useNotificationPermission } = await import("./use-notification-permission");
    const { result } = renderHook(() => useNotificationPermission());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.status).toBe("not_requested");
    expect(adapter.getPermissionStatus).toHaveBeenCalledTimes(1);
  });

  it("re-checks status when the native app resumes to the foreground", async () => {
    const { useNotificationPermission } = await import("./use-notification-permission");
    const { result } = renderHook(() => useNotificationPermission());
    await waitFor(() => expect(result.current.loading).toBe(false));

    adapter.refreshPermissionStatus.mockResolvedValue("granted");
    await act(async () => {
      appStateListener?.({ isActive: true });
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("granted"));
  });

  it("does not re-check when the app goes to the background (isActive: false)", async () => {
    const { useNotificationPermission } = await import("./use-notification-permission");
    const { result } = renderHook(() => useNotificationPermission());
    await waitFor(() => expect(result.current.loading).toBe(false));
    adapter.refreshPermissionStatus.mockClear();

    await act(async () => {
      appStateListener?.({ isActive: false });
      await Promise.resolve();
    });

    expect(adapter.refreshPermissionStatus).not.toHaveBeenCalled();
  });

  it("requestPermission updates status from the adapter's result", async () => {
    adapter.requestPermission.mockResolvedValue("denied");
    adapter.refreshPermissionStatus.mockResolvedValue("denied");
    const { useNotificationPermission } = await import("./use-notification-permission");
    const { result } = renderHook(() => useNotificationPermission());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.requestPermission();
    });

    expect(result.current.status).toBe("denied");
  });

  it("openSettings re-checks status afterward (covers 'returning from system settings')", async () => {
    adapter.refreshPermissionStatus.mockResolvedValue("granted");
    const { useNotificationPermission } = await import("./use-notification-permission");
    const { result } = renderHook(() => useNotificationPermission());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.openSettings();
    });

    expect(adapter.openSystemNotificationSettings).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.status).toBe("granted"));
  });

  it.each(["granted", "denied", "restricted", "not_requested"] as const)(
    "reflects a mocked adapter status of %s",
    async (status) => {
      adapter.getPermissionStatus.mockResolvedValue(status);
      const { useNotificationPermission } = await import("./use-notification-permission");
      const { result } = renderHook(() => useNotificationPermission());

      await waitFor(() => expect(result.current.status).toBe(status));
    },
  );
});
