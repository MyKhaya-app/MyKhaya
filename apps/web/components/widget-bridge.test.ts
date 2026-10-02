import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const setSnapshot = vi.fn<(options: { json: string }) => Promise<void>>().mockResolvedValue(undefined);
const clearSnapshotMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
const getCalendarRange = vi.fn();

vi.mock("@capacitor/core", () => ({
  registerPlugin: () => ({
    setSnapshot,
    getCalendarRange,
    clearSnapshot: clearSnapshotMock,
  }),
}));

const nativePlatformMock = vi.fn<() => "ios" | "android" | "web">(() => "ios");
vi.mock("./native-runtime", () => ({
  nativePlatform: () => nativePlatformMock(),
}));

interface MockHome {
  id: string;
  name: string;
}

const homesMock = vi.fn<() => Promise<MockHome[]>>();
const listEventsMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[]; next_page?: number | null }>>();
const sharesMock = vi.fn<(...args: unknown[]) => Promise<{ items: { id: string }[] }>>();
const sharedEventsMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
const routinesMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
const remindersMock = vi.fn<(...args: unknown[]) => Promise<{ items: unknown[] }>>();
vi.mock("@mykhaya/api-client", () => ({
  api: {
    homes: () => homesMock(),
    listEvents: (...args: unknown[]) => listEventsMock(...args),
    sharedCalendars: (...args: unknown[]) => sharesMock(...args),
    listSharedEvents: (...args: unknown[]) => sharedEventsMock(...args),
    routines: (...args: unknown[]) => routinesMock(...args),
    reminders: (...args: unknown[]) => remindersMock(...args),
  },
}));

const HOME: MockHome = { id: "home-1", name: "The Hales" };

interface MockSnapshotPayload {
  signedIn: boolean;
  activeHome: { id: string; displayName: string } | null;
  monthEvents: { id: string; title: string; colorHex: string }[];
}

function lastSnapshotPayload(): MockSnapshotPayload {
  const call = setSnapshot.mock.calls[0];
  if (!call) throw new Error("setSnapshot was never called");
  return JSON.parse(call[0].json) as MockSnapshotPayload;
}

describe("widget-bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nativePlatformMock.mockReturnValue("ios");
    getCalendarRange.mockResolvedValue({ startAt: "2026-09-28T00:00:00Z", endAt: "2026-10-05T00:00:00Z",
      startDate: "2026-09-28", endDate: "2026-10-05" });
    sharesMock.mockResolvedValue({ items: [] });
    sharedEventsMock.mockResolvedValue({ items: [] });
    homesMock.mockResolvedValue([HOME]);
    listEventsMock.mockResolvedValue({ items: [] });
    routinesMock.mockResolvedValue({ items: [] });
    remindersMock.mockResolvedValue({ items: [] });
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetModules();
  });

  it("is a no-op outside the native shell", async () => {
    nativePlatformMock.mockReturnValue("web");
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(homesMock).not.toHaveBeenCalled();
    expect(setSnapshot).not.toHaveBeenCalled();
  });

  it("is a no-op on Android — no WidgetBridge plugin exists there (regression: Android Phase 2B found this throwing uncaught inside nativeLogout(), silently aborting the post-logout redirect)", async () => {
    nativePlatformMock.mockReturnValue("android");
    const { syncWidgetSnapshot, clearWidgetSnapshot } = await import("./widget-bridge");
    await expect(syncWidgetSnapshot()).resolves.toBeUndefined();
    await expect(clearWidgetSnapshot()).resolves.toBeUndefined();
    expect(homesMock).not.toHaveBeenCalled();
    expect(setSnapshot).not.toHaveBeenCalled();
    expect(clearSnapshotMock).not.toHaveBeenCalled();
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
    nativePlatformMock.mockReturnValue("web");
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

  it("fetches every page and accepted shares, retaining only events overlapping the visible grid", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 28, 12));
    const event = (id: string, day: string, end: string) => ({ occurrence_id: id, event_id: id,
      title: id, start_at: `${day}T00:00:00Z`, end_at: `${end}T00:00:00Z`,
      is_all_day: true, timezone: "Europe/London", calendar_color: "#123456", label: null });
    listEventsMock.mockResolvedValueOnce({ items: [event("sep", "2026-09-28", "2026-09-29")], next_page: 2 })
      .mockResolvedValueOnce({ items: [event("trip", "2026-10-01", "2026-10-05"), event("outside", "2026-10-05", "2026-10-06")], next_page: null });
    sharesMock.mockResolvedValue({ items: [{ id: "share-1" }] });
    sharedEventsMock.mockResolvedValue({ items: [event("shared", "2026-10-03", "2026-10-04")] });
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(listEventsMock).toHaveBeenCalledTimes(2);
    expect(listEventsMock).toHaveBeenNthCalledWith(2, "home-1", expect.objectContaining({ page: 2, start_at: "2026-09-28T00:00:00.000Z" }));
    const query = listEventsMock.mock.calls[0]?.[1] as { start_at: string; end_at: string };
    expect(Date.parse(query.end_at)).toBeGreaterThanOrEqual(Date.parse("2026-10-05T00:00:00Z"));
    expect(sharedEventsMock).toHaveBeenCalledWith("share-1", expect.objectContaining({ start_at: "2026-09-28T00:00:00.000Z" }));
    expect(lastSnapshotPayload().monthEvents.map((e) => e.id)).toEqual(["sep", "trip", "shared"]);
    expect(lastSnapshotPayload().monthEvents[2]?.colorHex).toBe("#123456");
  });

  it("still syncs on installed binaries without the additive range method", async () => {
    getCalendarRange.mockRejectedValue(new Error("not implemented"));
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(setSnapshot).toHaveBeenCalledOnce();
  });

  it.each([
    ["2026-09-28T07:00:00Z", "2026-09-28T00:00:00.000Z"],
    ["2026-09-27T11:00:00Z", "2026-09-27T11:00:00.000Z"],
  ])("queries both timed and all-day boundaries without shifting event dates (%s)", async (startAt, expectedStart) => {
    getCalendarRange.mockResolvedValue({ startAt, endAt: "2026-10-05T07:00:00Z",
      startDate: "2026-09-28", endDate: "2026-10-05" });
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(listEventsMock).toHaveBeenCalledWith("home-1", expect.objectContaining({ start_at: expectedStart }));
  });

  it("does not retain stale shared data when a share is no longer authorised", async () => {
    sharesMock.mockResolvedValue({ items: [{ id: "revoked" }] });
    sharedEventsMock.mockRejectedValue(new Error("Forbidden"));
    const { syncWidgetSnapshot } = await import("./widget-bridge");
    await syncWidgetSnapshot();
    expect(lastSnapshotPayload().monthEvents).toEqual([]);
  });
});
