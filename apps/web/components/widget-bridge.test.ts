import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const setSnapshot = vi.fn<(options: { json: string }) => Promise<void>>().mockResolvedValue(undefined);
const clearSnapshotMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

vi.mock("@capacitor/core", () => ({
  registerPlugin: () => ({
    setSnapshot,
    clearSnapshot: clearSnapshotMock,
  }),
}));

const isNativeShellMock = vi.fn(() => true);
vi.mock("./native-runtime", () => ({
  isNativeShell: () => isNativeShellMock(),
}));

interface MockHome {
  id: string;
  name: string;
}

const homesMock = vi.fn<() => Promise<MockHome[]>>();
const listEventsMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
const routinesMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
const remindersMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
vi.mock("@mykhaya/api-client", () => ({
  api: {
    homes: () => homesMock(),
    listEvents: (...args: unknown[]) => listEventsMock(...args),
    routines: (...args: unknown[]) => routinesMock(...args),
    reminders: (...args: unknown[]) => remindersMock(...args),
  },
}));

const HOME: MockHome = { id: "home-1", name: "The Hales" };

interface MockSnapshotPayload {
  signedIn: boolean;
  activeHome: { id: string; displayName: string } | null;
}

function lastSnapshotPayload(): MockSnapshotPayload {
  const call = setSnapshot.mock.calls[0];
  if (!call) throw new Error("setSnapshot was never called");
  return JSON.parse(call[0].json) as MockSnapshotPayload;
}

describe("widget-bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isNativeShellMock.mockReturnValue(true);
    homesMock.mockResolvedValue([HOME]);
    listEventsMock.mockResolvedValue({ items: [] });
    routinesMock.mockResolvedValue({ items: [] });
    remindersMock.mockResolvedValue({ items: [] });
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it("is a no-op outside the native shell", async () => {
    isNativeShellMock.mockReturnValue(false);
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(homesMock).not.toHaveBeenCalled();
    expect(setSnapshot).not.toHaveBeenCalled();
  });

  it("writes an empty-home snapshot when there is no Home yet", async () => {
    homesMock.mockResolvedValue([]);
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(setSnapshot).toHaveBeenCalledTimes(1);
    const payload = lastSnapshotPayload();
    expect(payload.signedIn).toBe(true);
    expect(payload.activeHome).toBeNull();
  });

  it("fetches events/routines/reminders for the active Home and writes a snapshot", async () => {
    window.localStorage.setItem("mykhaya.activeHomeId", "home-1");
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(listEventsMock).toHaveBeenCalledWith("home-1", expect.any(Object));
    expect(routinesMock).toHaveBeenCalledWith("home-1");
    expect(remindersMock).toHaveBeenCalledWith("home-1");
    expect(setSnapshot).toHaveBeenCalledTimes(1);
    const payload = lastSnapshotPayload();
    expect(payload.activeHome).toEqual({ id: "home-1", displayName: "The Hales" });
  });

  it("falls back to the first Home when no active Home is stored", async () => {
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    const payload = lastSnapshotPayload();
    expect(payload.activeHome?.id).toBe("home-1");
  });

  it("clearWidgetSnapshot calls the native clear and never the setter", async () => {
    const { clearWidgetSnapshot } = await import("./widget-bridge");
    await clearWidgetSnapshot();
    expect(clearSnapshotMock).toHaveBeenCalledTimes(1);
    expect(setSnapshot).not.toHaveBeenCalled();
  });

  it("clearWidgetSnapshot is a no-op outside the native shell", async () => {
    isNativeShellMock.mockReturnValue(false);
    const { clearWidgetSnapshot } = await import("./widget-bridge");
    await clearWidgetSnapshot();
    expect(clearSnapshotMock).not.toHaveBeenCalled();
  });

  it("a sync failure does not throw — API errors degrade to an empty-ish snapshot", async () => {
    listEventsMock.mockRejectedValue(new Error("network"));
    routinesMock.mockRejectedValue(new Error("network"));
    remindersMock.mockRejectedValue(new Error("network"));
    window.localStorage.setItem("mykhaya.activeHomeId", "home-1");
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await expect(syncWidgetSnapshot()).resolves.toBeUndefined();
    expect(setSnapshot).toHaveBeenCalledTimes(1);
  });
});
