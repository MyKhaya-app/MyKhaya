import { afterEach, describe, expect, it, vi } from "vitest";

const { addListener } = vi.hoisted(() => ({ addListener: vi.fn() }));
vi.mock("@capacitor/app", () => ({
  App: { addListener },
}));

const {
  BIOMETRIC_LOCK_TIMEOUT_MS,
  hasEverBeenBackgrounded,
  markUnlocked,
  resetAppLockTrackingForTesting,
  shouldRequireUnlock,
  startAppLockTracking,
  wasBackgroundedLongEnoughToLock,
} = await import("./native-app-lock");

describe("shouldRequireUnlock", () => {
  it("always requires unlock when the app has never been backgrounded (cold launch)", () => {
    expect(shouldRequireUnlock(null, 1_000_000)).toBe(true);
  });

  it("does not require unlock for a short task switch", () => {
    const backgroundedAt = 1_000_000;
    const now = backgroundedAt + 30_000; // 30s later
    expect(shouldRequireUnlock(backgroundedAt, now)).toBe(false);
  });

  it("requires unlock after a long background period", () => {
    const backgroundedAt = 1_000_000;
    const now = backgroundedAt + BIOMETRIC_LOCK_TIMEOUT_MS + 1;
    expect(shouldRequireUnlock(backgroundedAt, now)).toBe(true);
  });

  it("treats exactly the timeout boundary as requiring unlock", () => {
    const backgroundedAt = 1_000_000;
    const now = backgroundedAt + BIOMETRIC_LOCK_TIMEOUT_MS;
    expect(shouldRequireUnlock(backgroundedAt, now)).toBe(true);
  });

  it("honours a custom timeout override", () => {
    const backgroundedAt = 1_000_000;
    const now = backgroundedAt + 10_000;
    expect(shouldRequireUnlock(backgroundedAt, now, 5_000)).toBe(true);
    expect(shouldRequireUnlock(backgroundedAt, now, 60_000)).toBe(false);
  });
});

describe("startAppLockTracking / wasBackgroundedLongEnoughToLock", () => {
  afterEach(() => {
    resetAppLockTrackingForTesting();
    vi.clearAllMocks();
  });

  it("records a background transition via the appStateChange listener", async () => {
    startAppLockTracking();
    expect(addListener).toHaveBeenCalledWith("appStateChange", expect.any(Function));
    const handler = addListener.mock.calls[0]?.[1] as (info: { isActive: boolean }) => void;

    handler({ isActive: false });

    expect(wasBackgroundedLongEnoughToLock(Date.now() + BIOMETRIC_LOCK_TIMEOUT_MS + 1)).toBe(true);
  });

  it("does not require unlock for a short background dip", async () => {
    startAppLockTracking();
    const handler = addListener.mock.calls[0]?.[1] as (info: { isActive: boolean }) => void;
    const backgroundedAt = Date.now();

    handler({ isActive: false });

    expect(wasBackgroundedLongEnoughToLock(backgroundedAt + 1_000)).toBe(false);
  });

  it("only attaches the listener once across repeated calls", () => {
    startAppLockTracking();
    startAppLockTracking();
    startAppLockTracking();

    expect(addListener).toHaveBeenCalledTimes(1);
  });

  it("markUnlocked clears the recorded background time so the next short dip is judged on its own merits", () => {
    startAppLockTracking();
    const handler = addListener.mock.calls[0]?.[1] as (info: { isActive: boolean }) => void;
    handler({ isActive: false });
    markUnlocked();

    // A fresh background dip that happens *after* unlocking must be judged
    // on its own elapsed time, not any timestamp from before the unlock.
    handler({ isActive: false });
    expect(wasBackgroundedLongEnoughToLock(Date.now() + 1_000)).toBe(false);
  });
});

describe("hasEverBeenBackgrounded", () => {
  afterEach(() => {
    resetAppLockTrackingForTesting();
    vi.clearAllMocks();
  });

  it("is false before any background transition has been recorded", () => {
    expect(hasEverBeenBackgrounded()).toBe(false);
  });

  it("becomes true once a background transition is recorded", () => {
    startAppLockTracking();
    const handler = addListener.mock.calls[0]?.[1] as (info: { isActive: boolean }) => void;

    handler({ isActive: false });

    expect(hasEverBeenBackgrounded()).toBe(true);
  });

  it("goes back to false after markUnlocked — a resume handler must not treat this as 'still backgrounded'", () => {
    startAppLockTracking();
    const handler = addListener.mock.calls[0]?.[1] as (info: { isActive: boolean }) => void;
    handler({ isActive: false });
    expect(hasEverBeenBackgrounded()).toBe(true);

    markUnlocked();

    expect(hasEverBeenBackgrounded()).toBe(false);
  });

  it("an isActive:true firing with no prior background is distinguishable via this flag even though shouldRequireUnlock(null, ...) alone would say true", () => {
    // This is the exact scenario the flag exists for: some platforms send
    // one appStateChange(isActive:true) during ordinary startup, with no
    // preceding isActive:false. wasBackgroundedLongEnoughToLock() alone
    // (built on shouldRequireUnlock's null-means-true default) cannot tell
    // this apart from "backgrounded forever" — hasEverBeenBackgrounded()
    // is what lets a caller correctly do nothing here instead.
    expect(hasEverBeenBackgrounded()).toBe(false);
    expect(wasBackgroundedLongEnoughToLock()).toBe(true);
  });
});
