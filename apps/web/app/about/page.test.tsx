import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import About from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/about",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
    },
  };
});

const { isNativeShell } = vi.hoisted(() => ({ isNativeShell: vi.fn(() => false) }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell }));

const { getInfo } = vi.hoisted(() => ({ getInfo: vi.fn() }));
vi.mock("@capacitor/app", () => ({ App: { getInfo } }));

const nativePermission = vi.hoisted(() => ({
  status: "granted" as "not_requested" | "granted" | "denied" | "restricted" | "unsupported",
  loading: false,
  requestPermission: vi.fn(),
  openSettings: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("@/components/use-notification-permission", () => ({
  useNotificationPermission: () => nativePermission,
}));

const nativePushDiagnostics = vi.hoisted(() => vi.fn(() => ({ tokenPresent: false, registered: false })));
vi.mock("@/components/native-push", () => ({ nativePushDiagnostics }));

const { api } = await import("@mykhaya/api-client");

function mockBuild(payload: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(payload),
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
  isNativeShell.mockReturnValue(false);
  nativePermission.status = "granted";
  nativePushDiagnostics.mockReturnValue({ tokenPresent: false, registered: false });
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
});

describe("About — browser", () => {
  it("shows the Web version and no iOS app row", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText(/iOS app/i)).not.toBeInTheDocument();
    expect(getInfo).not.toHaveBeenCalled();
  });

  it("does not show an Environment row in production", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText("Environment")).not.toBeInTheDocument();
  });

  it("shows a Development environment row only on a development build", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "development", channel: "development" });

    render(<About />);

    await screen.findByText("Development");
  });
});

describe("About — native iOS", () => {
  beforeEach(() => {
    isNativeShell.mockReturnValue(true);
  });

  it("shows the iOS app version and build number alongside the Web version", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    getInfo.mockResolvedValue({ name: "MyKhaya", id: "app.mykhaya", build: "8", version: "0.1.0" });

    render(<About />);

    await waitFor(() => expect(screen.getByText(/0\.1\.0 \(Build 8\)/)).toBeInTheDocument());
    expect(screen.getByText("iOS app")).toBeInTheDocument();
    expect(screen.getByText("Web")).toBeInTheDocument();
  });

  it("omits the iOS app row rather than showing fake data when native metadata fails", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    getInfo.mockRejectedValue(new Error("unavailable"));

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText("iOS app")).not.toBeInTheDocument();
  });
});

describe("About — native Notifications diagnostics", () => {
  beforeEach(() => {
    isNativeShell.mockReturnValue(true);
  });

  it("does not appear at all outside the native shell", async () => {
    isNativeShell.mockReturnValue(false);
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText("Notification permission")).not.toBeInTheDocument();
  });

  it("shows the live permission status independent of push-registration state", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePermission.status = "granted";
    nativePushDiagnostics.mockReturnValue({ tokenPresent: false, registered: false });

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.getByText("Granted")).toBeInTheDocument();
    expect(screen.getByText("Not registered")).toBeInTheDocument();
    expect(screen.getByText("Not present")).toBeInTheDocument();
  });

  it("shows Registered/Present when a device has registered", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Registered");
    expect(screen.getByText("Present")).toBeInTheDocument();
  });

  it("never shows the raw device token — only masked Present/Not present", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Present");
    expect(screen.queryByText("native-token")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{32,}/i);
  });

  it("shows Push provider as APNs", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("Push provider");
    expect(screen.getByText("APNs")).toBeInTheDocument();
  });

  it("omits the Last registration row rather than showing a fake value when never registered", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    window.localStorage.removeItem("mykhaya.native.push.last-registered-at");

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.queryByText("Last registration")).not.toBeInTheDocument();
  });

  it("shows a formatted Last registration timestamp when one is present", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    window.localStorage.setItem("mykhaya.native.push.last-registered-at", String(Date.UTC(2026, 0, 1)));

    render(<About />);

    await screen.findByText("Last registration");
    window.localStorage.removeItem("mykhaya.native.push.last-registered-at");
  });

  it("shows Off when notification permission is denied, distinct from push-registration status", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePermission.status = "denied";
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.getByText("Off")).toBeInTheDocument();
    // Registration can still show "Registered" even though permission now
    // reads denied (e.g. revoked after a previous successful registration) —
    // the two are independent facts, neither overwrites the other.
    expect(screen.getByText("Registered")).toBeInTheDocument();
  });
});

describe("About — Service Status link", () => {
  it("links to the existing Service Status page", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toHaveAttribute("href", "/service-status");
  });
});
