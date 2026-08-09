import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@mykhaya/api-client", () => ({
  api: {
    pushPublicKey: vi.fn(),
    registerPushSubscription: vi.fn(),
  },
}));

vi.mock("./install-prompt", () => ({
  isStandalone: () => true,
}));

// Imported after the mocks above so subscribeToPush picks up the mocked api client.
const { api } = await import("@mykhaya/api-client");
const { subscribeToPush, diagnosePushEnvironment } = await import("./push-subscribe");

type MockRegistration = {
  pushManager: {
    getSubscription: ReturnType<typeof vi.fn>;
    subscribe: ReturnType<typeof vi.fn>;
  };
};

function fakeSubscription() {
  return {
    toJSON: () => ({
      endpoint: "https://push.example/abc",
      keys: { p256dh: "p256dh-value", auth: "auth-value" },
    }),
  };
}

function stubBrowser(options: {
  serviceWorkerReady?: Promise<MockRegistration> | (() => Promise<MockRegistration>);
  permission?: NotificationPermission;
  requestPermission?: () => Promise<NotificationPermission>;
} = {}) {
  const registration: MockRegistration = {
    pushManager: {
      getSubscription: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn().mockResolvedValue(fakeSubscription()),
    },
  };
  const readyValue = options.serviceWorkerReady ?? Promise.resolve(registration);
  const ready = typeof readyValue === "function" ? readyValue() : readyValue;

  vi.stubGlobal("window", { PushManager: class {} });
  vi.stubGlobal("navigator", {
    serviceWorker: {
      ready,
      controller: null,
      getRegistration: vi.fn().mockResolvedValue(undefined),
    },
    userAgent: "test-agent",
  });
  vi.stubGlobal("Notification", {
    permission: options.permission ?? "default",
    requestPermission: options.requestPermission ?? vi.fn().mockResolvedValue("granted"),
  });

  return registration;
}

describe("subscribeToPush", () => {
  beforeEach(() => {
    vi.mocked(api.pushPublicKey).mockResolvedValue({ configured: true, public_key: "AAAA" });
    vi.mocked(api.registerPushSubscription).mockResolvedValue({ id: "sub-1" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns unsupported when the browser has no PushManager", async () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("navigator", { serviceWorker: {} });
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "unsupported" });
  });

  it("returns permission-denied without prompting when already denied", async () => {
    const requestPermission = vi.fn();
    stubBrowser({ permission: "denied", requestPermission });
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "permission-denied" });
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("returns permission-denied when the user declines the prompt", async () => {
    stubBrowser({ requestPermission: vi.fn().mockResolvedValue("denied") });
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "permission-denied" });
  });

  it("returns not-configured when the server has no VAPID key", async () => {
    vi.mocked(api.pushPublicKey).mockResolvedValue({ configured: false, public_key: null });
    stubBrowser();
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "not-configured" });
  });

  it("returns error when the VAPID key request fails", async () => {
    vi.mocked(api.pushPublicKey).mockRejectedValue(new Error("network down"));
    stubBrowser();
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "error" });
  });

  it("returns error when backend subscription registration fails", async () => {
    vi.mocked(api.registerPushSubscription).mockRejectedValue(new Error("500"));
    stubBrowser();
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: false, reason: "error", stage: undefined });
  });

  it("succeeds end to end and reports every stage in order", async () => {
    stubBrowser();
    const stages: string[] = [];
    const result = await subscribeToPush((stage) => stages.push(stage));
    expect(result).toEqual({ ok: true });
    expect(stages).toEqual([
      "checking-support",
      "checking-permission",
      "requesting-permission",
      "fetching-public-key",
      "waiting-for-service-worker",
      "checking-existing-subscription",
      "creating-push-subscription",
      "registering-with-api",
      "complete",
    ]);
  });

  it("reuses an existing subscription instead of creating a new one", async () => {
    const registration = stubBrowser();
    registration.pushManager.getSubscription.mockResolvedValue(fakeSubscription());
    const result = await subscribeToPush();
    expect(result).toEqual({ ok: true });
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("times out and reports the stuck stage when the service worker never becomes ready", async () => {
    vi.useFakeTimers();
    // A promise that never settles — the exact "awaited browser promise never
    // resolves" scenario the timeout mechanism exists for.
    stubBrowser({ serviceWorkerReady: () => new Promise(() => {}) });

    const stages: string[] = [];
    const pending = subscribeToPush((stage) => stages.push(stage));
    await vi.advanceTimersByTimeAsync(12_000);
    const result = await pending;

    expect(result).toEqual({ ok: false, reason: "timeout", stage: "waiting-for-service-worker" });
    expect(stages.at(-1)).toBe("waiting-for-service-worker");
  });
});

describe("diagnosePushEnvironment", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never includes subscription endpoint or key data", async () => {
    stubBrowser();
    const diagnostics = await diagnosePushEnvironment();
    const serialised = JSON.stringify(diagnostics);
    expect(serialised).not.toMatch(/p256dh|auth-value|endpoint/i);
    expect(diagnostics.pushManagerAvailable).toBe(true);
  });
});
