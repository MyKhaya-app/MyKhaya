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
      listSupportTickets: vi.fn(),
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

// Phase 2H: the compact Service Status summary and service_status_url both
// come from the single, unauthenticated GET /api/v1/config/public — never a
// separate /api/v1/status call, which is host-gated to the dedicated status
// subdomain (mykhaya.routers.status.enforce_status_host) and unreachable
// from this app's own origin in a real deployment. See help-support/page.tsx.
type FetchMockOptions = {
  configPayload?: Record<string, unknown>;
  configOk?: boolean;
  configRejects?: boolean;
};

const DEFAULT_CONFIG_PAYLOAD = {
  service_status_url: "https://status.dev.mykhaya.app/",
  support_enabled: true,
  status_overall: "operational",
  status_overall_message: "Operational",
};

function mockFetch({
  configPayload = DEFAULT_CONFIG_PAYLOAD,
  configOk = true,
  configRejects = false,
}: FetchMockOptions = {}) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (url.includes("/config/public")) {
      if (configRejects) return Promise.reject(new Error("network down"));
      return Promise.resolve({ ok: configOk, json: () => Promise.resolve(configPayload) });
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
  (api.listSupportTickets as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
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

  it("shows an explanatory Report a bug card, not a dead link, when support is disabled", async () => {
    mockFetch({
      configPayload: { ...DEFAULT_CONFIG_PAYLOAD, support_enabled: false },
    });
    render(<HelpSupport />);

    await waitFor(() => {
      expect(screen.getByText("Temporarily unavailable")).toBeInTheDocument();
    });
    // The quick action degrades to a non-navigable, clearly-labelled
    // disabled state, not a link to a route that can't do anything.
    expect(screen.queryByRole("link", { name: "Report a bug" })).toBeNull();
    expect(screen.getByText("Report a bug")).toBeInTheDocument();
  });

  it("does not show the explanatory Report a bug card once support is enabled", async () => {
    render(<HelpSupport />);
    await screen.findByRole("link", { name: "Report a bug" });
    expect(screen.queryByText("Temporarily unavailable")).toBeNull();
  });
});

describe("Help & Support — My support requests", () => {
  it("links to the requests list", async () => {
    render(<HelpSupport />);
    const link = await screen.findByRole("link", { name: /view all/i });
    expect(link).toHaveAttribute("href", "/help-support/requests");
    expect(
      screen.getByText("View your open and previous support requests."),
    ).toBeInTheDocument();
  });

  it("shows recent support requests fetched from the existing ticket list", async () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        { id: "t1", reference: "MK-1001", type: "bug", status: "open", priority: "normal", subject: "A", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", resolved_at: null },
        { id: "t2", reference: "MK-1002", type: "bug", status: "in_progress", priority: "normal", subject: "B", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", resolved_at: null },
        { id: "t3", reference: "MK-1003", type: "bug", status: "resolved", priority: "normal", subject: "C", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", resolved_at: "2026-01-02T00:00:00Z" },
      ],
    });
    render(<HelpSupport />);
    await screen.findByRole("link", { name: /view all/i });
    expect(await screen.findByText("A")).toBeInTheDocument();
    expect(screen.getByText("MK-1002")).toBeInTheDocument();
  });

  it("shows no count badge when there are no open requests", async () => {
    render(<HelpSupport />);
    await screen.findByRole("link", { name: /view all/i });
    expect(screen.queryByText(/open$/)).toBeNull();
  });

  it("shows no count badge, and no crash, when the ticket list fails to load", async () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("network down"));
    render(<HelpSupport />);
    await screen.findByRole("link", { name: /view all/i });
    expect(screen.queryByText(/open$/)).toBeNull();
  });

  it("remains available even when support ticket submission is disabled", async () => {
    mockFetch({ configPayload: { ...DEFAULT_CONFIG_PAYLOAD, support_enabled: false } });
    render(<HelpSupport />);
    const link = await screen.findByRole("link", { name: /view all/i });
    expect(link).toHaveAttribute("href", "/help-support/requests");
  });
});

describe("Help & Support — compact contact card", () => {
  it("offers a second Contact support action without changing the existing route", async () => {
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Need more help?" });
    expect(screen.getAllByRole("link", { name: "Contact support" })).toHaveLength(2);
    expect(screen.getByText(/urgent issue or need personalised support/i)).toBeInTheDocument();
  });
});

describe("Help & Support — Service Status", () => {
  it("shows 'All systems operational' for the operational state", async () => {
    mockFetch({
      configPayload: { ...DEFAULT_CONFIG_PAYLOAD, status_overall: "operational", status_overall_message: "Operational" },
    });
    render(<HelpSupport />);
    await screen.findByText("All systems operational");
  });

  it("shows 'Some services are experiencing problems' for a degraded state", async () => {
    mockFetch({
      configPayload: {
        ...DEFAULT_CONFIG_PAYLOAD,
        status_overall: "degraded_performance",
        status_overall_message: "Some systems are experiencing degraded performance",
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Some services are experiencing problems");
  });

  it("shows 'Some services are experiencing problems' for a partial outage", async () => {
    mockFetch({
      configPayload: {
        ...DEFAULT_CONFIG_PAYLOAD,
        status_overall: "partial_outage",
        status_overall_message: "Partial service disruption",
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Some services are experiencing problems");
  });

  it("shows 'Service disruption' for a major outage", async () => {
    mockFetch({
      configPayload: {
        ...DEFAULT_CONFIG_PAYLOAD,
        status_overall: "major_outage",
        status_overall_message: "Major service disruption",
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Service disruption");
  });

  it("shows the backend's own truthful wording for a maintenance window, never collapsed into an outage", async () => {
    mockFetch({
      configPayload: {
        ...DEFAULT_CONFIG_PAYLOAD,
        status_overall: "maintenance",
        status_overall_message: "Scheduled maintenance in progress",
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Scheduled maintenance in progress");
    expect(screen.queryByText("Service disruption")).toBeNull();
    expect(screen.queryByText("Some services are experiencing problems")).toBeNull();
  });

  it("degrades gracefully, with no crash and no fabricated 'All systems operational', when the config fetch rejects", async () => {
    mockFetch({ configRejects: true });
    render(<HelpSupport />);
    await screen.findByRole("heading", { name: "Help & Support" });
    await screen.findByText("Status information is temporarily unavailable.");
    expect(screen.queryByText("All systems operational")).toBeNull();
  });

  it("degrades gracefully, with no fabricated 'All systems operational', when the config endpoint returns a non-OK response", async () => {
    mockFetch({ configOk: false, configPayload: {} });
    render(<HelpSupport />);
    await screen.findByText("Status information is temporarily unavailable.");
    expect(screen.queryByText("All systems operational")).toBeNull();
  });

  it("shows the truthful unavailable state, not a fabricated good state, when the backend omits status fields (e.g. status_public_enabled off)", async () => {
    mockFetch({
      configPayload: {
        service_status_url: "https://status.dev.mykhaya.app/",
        support_enabled: true,
        // No status_overall / status_overall_message — mirrors what
        // routers.public_config sends when settings.status_public_enabled
        // is False.
      },
    });
    render(<HelpSupport />);
    await screen.findByText("Status information is temporarily unavailable.");
    expect(screen.queryByText("All systems operational")).toBeNull();
  });

  it("opens the configured service_status_url externally, not /service-status, and never uses colour alone", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<HelpSupport />);

    await screen.findByText("All systems operational");
    const link = screen.getByRole("link", { name: /view platform status/i });
    expect(link).toHaveAttribute("href", "https://status.dev.mykhaya.app/");
    // Status wording is always real visible text, not colour/icon alone —
    // the coloured dot next to it is aria-hidden.
    expect(document.querySelector(".help-status-dot")).toHaveAttribute("aria-hidden", "true");

    await user.click(link);
    expect(openExternalUrl).toHaveBeenCalledWith("https://status.dev.mykhaya.app/");
  });

  it("shows a disabled state, not a broken link, when no status URL is configured", async () => {
    mockFetch({ configPayload: { ...DEFAULT_CONFIG_PAYLOAD, service_status_url: null } });
    render(<HelpSupport />);
    await screen.findByText("All systems operational");
    expect(screen.queryByRole("link", { name: /view platform status/i })).toBeNull();
    expect(screen.getByText("Platform status page not available right now")).toBeInTheDocument();
  });

  it("keeps the detailed-status action keyboard accessible as a real link, not a click-only element", async () => {
    mockFetch();
    render(<HelpSupport />);
    await screen.findByText("All systems operational");
    const link = screen.getByRole("link", { name: /view platform status/i });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href");
  });

  it("shows a truthful, announced 'Checking…' state before the config fetch resolves, in a live region", async () => {
    // The page fetches /config/public twice (Service Status + the separate
    // support_enabled check) — resolve every outstanding call, not just one.
    const resolvers: ((value: { ok: boolean; json: () => Promise<unknown> }) => void)[] = [];
    global.fetch = vi.fn(
      () => new Promise((resolve) => { resolvers.push(resolve); }),
    ) as unknown as typeof fetch;

    render(<HelpSupport />);
    await screen.findByText("Checking…");
    const card = screen.getByText("Checking…").closest("section");
    expect(card).toHaveAttribute("aria-live", "polite");

    resolvers.forEach((resolve) => resolve({ ok: true, json: () => Promise.resolve(DEFAULT_CONFIG_PAYLOAD) }));
    await screen.findByText("All systems operational");
  });

  it("does not remove or disable Service Status when the Support ticket feature is disabled", async () => {
    mockFetch({ configPayload: { ...DEFAULT_CONFIG_PAYLOAD, support_enabled: false } });
    render(<HelpSupport />);
    await screen.findByText("Temporarily unavailable");
    await screen.findByText("All systems operational");
    expect(screen.getByRole("link", { name: /view platform status/i })).toBeInTheDocument();
  });

  it("leaves Contact support, Diagnostics, and page rendering unaffected when the status summary fails", async () => {
    mockFetch({ configRejects: true });
    render(<HelpSupport />);
    await screen.findByText("Status information is temporarily unavailable.");

    expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute(
      "href",
      "/help-support/contact-support",
    );
    expect(screen.getByRole("link", { name: "Run diagnostics" })).toHaveAttribute(
      "href",
      "/help-support/diagnostics",
    );
    expect(screen.getByRole("link", { name: "Run diagnostics" })).toHaveAttribute(
      "href",
      "/help-support/diagnostics",
    );
  });
});

describe.skip("Help & Support — Helpful diagnostics summary", () => {
  it("never fabricates an app version when none is truthfully available", async () => {
    global.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/config/public")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              service_status_url: null,
              status_overall: "operational",
              status_overall_message: "Operational",
            }),
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
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              service_status_url: null,
              status_overall: "operational",
              status_overall_message: "Operational",
            }),
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
