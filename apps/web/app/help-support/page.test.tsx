import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HelpSupport from "./page";

const { openExternalUrl } = vi.hoisted(() => ({ openExternalUrl: vi.fn() }));
vi.mock("@/components/open-external-url", () => ({ openExternalUrl }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support",
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

const { isNativeShell, nativePlatform } = vi.hoisted(() => ({
  isNativeShell: vi.fn(() => false),
  nativePlatform: vi.fn(() => "web" as "ios" | "android" | "web"),
}));
vi.mock("@/components/native-runtime", () => ({ isNativeShell, nativePlatform }));

const { getInfo } = vi.hoisted(() => ({ getInfo: vi.fn() }));
vi.mock("@capacitor/app", () => ({ App: { getInfo } }));

const notificationPermission = vi.hoisted(() => ({
  status: "granted" as "not_requested" | "granted" | "denied" | "restricted" | "unsupported",
  loading: false,
  requestPermission: vi.fn(),
  openSettings: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("@/components/use-notification-permission", () => ({
  useNotificationPermission: () => notificationPermission,
}));

const { api } = await import("@mykhaya/api-client");

type FetchMockOptions = {
  configPayload?: unknown;
  statusPayload?: unknown;
  statusOk?: boolean;
  statusRejects?: boolean;
};

function mockFetch({
  configPayload = { service_status_url: "https://status.dev.mykhaya.app/" },
  statusPayload = { overall: "operational", overall_message: "Operational" },
  statusOk = true,
  statusRejects = false,
}: FetchMockOptions = {}) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (url.includes("/config/public")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(configPayload) });
    }
    if (url.includes("/status")) {
      if (statusRejects) return Promise.reject(new Error("network down"));
      return Promise.resolve({ ok: statusOk, json: () => Promise.resolve(statusPayload) });
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
  isNativeShell.mockReturnValue(false);
  nativePlatform.mockReturnValue("web");
  notificationPermission.status = "granted";
  Object.defineProperty(window.navigator, "onLine", { value: true, configurable: true });
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  mockFetch();
});

describe("Help & Support — page structure", () => {
  it("renders the agreed heading and subtitle", async () => {
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Help & Support" });
    expect(
      screen.getByText("Get help, report issues, and check your app health."),
    ).toBeInTheDocument();
  });
});

describe("Help & Support — quick actions", () => {
  it("renders all three quick actions with accessible labels and correct destinations", async () => {
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Help & Support" });

    // Exact match: the quick action's accessible name is just its label
    // (icon is aria-hidden), while the card below shares the same words but
    // also includes its description text — exact matching disambiguates
    // the two.
    const reportBug = screen.getByRole("link", { name: "Report a bug" });
    const contactSupport = screen.getByRole("link", { name: "Contact support" });
    const runDiagnostics = screen.getByRole("link", { name: "Run diagnostics" });

    expect(reportBug).toHaveAttribute("href", "/help-support/report-bug");
    expect(contactSupport).toHaveAttribute("href", "/help-support/contact-support");
    expect(runDiagnostics).toHaveAttribute("href", "/help-support/diagnostics");
  });

  it("makes the Report a bug and Contact support cards below navigate to the same real placeholder routes", async () => {
    render(<HelpSupport />);
    const reportBugHeading = await screen.findByRole("heading", { name: "Report a bug" });
    const contactSupportHeading = screen.getByRole("heading", { name: "Contact support" });

    expect(reportBugHeading.closest("a")).toHaveAttribute("href", "/help-support/report-bug");
    expect(contactSupportHeading.closest("a")).toHaveAttribute("href", "/help-support/contact-support");
  });
});

describe("Help & Support — Knowledge base", () => {
  it("remains truthfully Coming soon, with no link and no fabricated content", async () => {
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Knowledge base" });
    expect(screen.getByText("Find answers and guidance for using MyKhaya.")).toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: "Knowledge base" });
    expect(heading.closest("a")).toBeNull();
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThan(0);
  });
});

describe("Help & Support — Service Status", () => {
  it("shows 'All systems operational' for the operational state", async () => {
    mockFetch({ statusPayload: { overall: "operational", overall_message: "Operational" } });
    render(<HelpSupport />);
    await screen.findByText("All systems operational");
  });

  it("shows 'Some services are experiencing problems' for a degraded state", async () => {
    mockFetch({
      statusPayload: {
        overall: "degraded_performance",
        overall_message: "Some systems are experiencing degraded performance",
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Some services are experiencing problems");
  });

  it("shows 'Service disruption' for a major outage", async () => {
    mockFetch({ statusPayload: { overall: "major_outage", overall_message: "Major service disruption" } });
    render(<HelpSupport />);
    await screen.findByText("Service disruption");
  });

  it("degrades gracefully, with no crash, when the status API fails", async () => {
    mockFetch({ statusRejects: true });
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Help & Support" });
    await screen.findByText("Status information is temporarily unavailable.");
  });

  it("degrades gracefully when the status API returns a non-OK response", async () => {
    mockFetch({ statusOk: false, statusPayload: {} });
    render(<HelpSupport />);
    await screen.findByText("Status information is temporarily unavailable.");
  });

  it("opens the configured service_status_url externally, not /service-status, and never uses colour alone", async () => {
    mockFetch({ configPayload: { service_status_url: "https://status.dev.mykhaya.app/" } });
    const user = userEvent.setup();
    render(<HelpSupport />);

    await screen.findByText("All systems operational");
    const link = screen.getByRole("link", { name: /view current platform status/i });
    expect(link).toHaveAttribute("href", "https://status.dev.mykhaya.app/");

    await user.click(link);
    expect(openExternalUrl).toHaveBeenCalledWith("https://status.dev.mykhaya.app/");
  });

  it("shows a disabled state, not a broken link, when no status URL is configured", async () => {
    mockFetch({ configPayload: { service_status_url: null } });
    render(<HelpSupport />);
    await screen.findByText("All systems operational");
    expect(screen.queryByRole("link", { name: /view current platform status/i })).toBeNull();
    expect(screen.getByText("Platform status page not available right now")).toBeInTheDocument();
  });
});

describe("Help & Support — Helpful diagnostics summary", () => {
  it("never fabricates an app version when none is truthfully available", async () => {
    global.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/config/public")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ service_status_url: null }) });
      }
      if (url.includes("/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ overall: "operational", overall_message: "Operational" }),
        });
      }
      // /api/v1/health/build genuinely fails — the truthful "unavailable" path.
      return Promise.reject(new Error("no build info"));
    }) as unknown as typeof fetch;

    render(<HelpSupport />);
    await screen.findByText("Helpful diagnostics");
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
  });

  it("shows the real web app version once it loads", async () => {
    global.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/config/public")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ service_status_url: null }) });
      }
      if (url.includes("/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ overall: "operational", overall_message: "Operational" }),
        });
      }
      if (url.includes("/health/build")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              version: "1.4.0",
              commit: "abc",
              build_time: "now",
              environment: "production",
              channel: "stable",
            }),
        });
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    }) as unknown as typeof fetch;

    render(<HelpSupport />);
    await waitFor(() => expect(screen.getByText("1.4.0")).toBeInTheDocument());
    expect(getInfo).not.toHaveBeenCalled(); // web, not native — never asks Capacitor
  });

  it("shows the truthful platform label", async () => {
    nativePlatform.mockReturnValue("web");
    render(<HelpSupport />);
    await screen.findByText("Helpful diagnostics");
    expect(screen.getByText("Web browser")).toBeInTheDocument();
  });

  it("shows the truthful notification permission state", async () => {
    notificationPermission.status = "denied";
    render(<HelpSupport />);
    await screen.findByText("Helpful diagnostics");
    expect(screen.getByText("Off")).toBeInTheDocument();
  });

  it("shows the truthful connectivity state", async () => {
    Object.defineProperty(window.navigator, "onLine", { value: false, configurable: true });
    render(<HelpSupport />);
    await screen.findByText("Helpful diagnostics");
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });
});
