import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import HealthPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/health",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const response = {
  overall: "Healthy",
  checked_at: "2026-09-07T09:00:00Z",
  services: [
    {
      service: "Database",
      state: "Healthy",
      explanation: "All connections nominal.",
      last_checked: "2026-09-07T09:00:00Z",
      last_success: "2026-09-07T09:00:00Z",
      last_failure: null,
      recommended_action: null,
    },
    {
      service: "Email provider",
      state: "Degraded",
      explanation: "Elevated latency.",
      last_checked: "2026-09-07T09:00:00Z",
      last_success: "2026-09-07T08:00:00Z",
      last_failure: "2026-09-07T08:30:00Z",
      recommended_action: "Check provider status page.",
    },
  ],
};

const actor = { id: "op-1", email: "op@mykhaya.app", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" as const };

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    return Promise.resolve(response);
  });
});

describe("Health", () => {
  it("renders the page heading and the overall Health banner", async () => {
    render(<HealthPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Health" })).toBeInTheDocument();
    expect((await screen.findAllByText("Healthy")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Checked/)).toBeInTheDocument();
  });

  it("renders each service as a card with its name as a semantic heading", async () => {
    render(<HealthPage />);
    expect(await screen.findByRole("heading", { name: "Database" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Email provider" })).toBeInTheDocument();
    expect(screen.getByText("All connections nominal.")).toBeInTheDocument();
    expect(screen.getByText("Elevated latency.")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });

  it("shows the operator action for a service that has one, and none for a service without one", async () => {
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Email provider" });
    expect(screen.getByText("Check provider status page.")).toBeInTheDocument();
    // Database has no recommended_action — no "None required" filler text anywhere.
    expect(screen.queryByText(/None required/)).not.toBeInTheDocument();
  });

  it("renders a service with no components field without crashing or showing a component grid", async () => {
    render(<HealthPage />);
    const databaseHeading = await screen.findByRole("heading", { name: "Database" });
    const card = databaseHeading.closest(".cc-card");
    expect(card).not.toBeNull();
    expect((card as HTMLElement).querySelector(".cc-record-list-grid")).toBeNull();
  });

  it("shows a loading state before data arrives", () => {
    get.mockImplementation(() => new Promise(() => {}));
    render(<HealthPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an empty state when no services are returned", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve({ overall: "Healthy", checked_at: "2026-09-07T09:00:00Z", services: [] });
    });
    render(<HealthPage />);
    expect(await screen.findByText("No health checks returned.")).toBeInTheDocument();
  });

  it("shows a safe error message when the health check fails", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.reject(new ApiError(500, "Something went wrong. Please try again."));
    });
    render(<HealthPage />);
    expect(await screen.findByText(/Health checks are unavailable/)).toBeInTheDocument();
  });
});

describe("Health — Push notifications dedicated card", () => {
  function pushResponse(overrides: {
    state: string;
    explanation: string;
    components: Array<{
      name: string;
      state: string;
      successes_24h: number;
      failures_24h: number;
      failing_devices: number;
    }>;
  }) {
    return {
      overall: "Healthy",
      checked_at: "2026-09-07T09:00:00Z",
      services: [
        {
          service: "Push notifications",
          state: overrides.state,
          explanation: overrides.explanation,
          last_checked: "2026-09-07T09:00:00Z",
          last_success: "2026-09-07T09:00:00Z",
          last_failure: null,
          recommended_action: null,
          components: overrides.components,
        },
      ],
    };
  }

  const fiveHealthyComponents = [
    { name: "Production APNs", state: "Healthy", successes_24h: 8, failures_24h: 0, failing_devices: 0 },
    { name: "Sandbox APNs", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
    { name: "Android FCM", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
    { name: "Web Push", state: "Healthy", successes_24h: 19, failures_24h: 0, failing_devices: 0 },
    { name: "Legacy iOS", state: "Healthy", successes_24h: 28, failures_24h: 0, failing_devices: 0 },
  ];

  it("renders Push notifications as its own card with a heading and state badge", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "All production-relevant push components are healthy.",
          components: fiveHealthyComponents,
        })
      );
    });
    render(<HealthPage />);
    const heading = await screen.findByRole("heading", { name: "Push notifications" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("All production-relevant push components are healthy.")).toBeInTheDocument();
  });

  it("renders all five push component cards with their names and status", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "All production-relevant push components are healthy.",
          components: fiveHealthyComponents,
        })
      );
    });
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Push notifications" });

    for (const name of ["Production APNs", "Sandbox APNs", "Android FCM", "Web Push", "Legacy iOS"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("shows per-component success and failure counts without a nested table", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Degraded",
          explanation: "Production APNs is failing in the last 24 hours.",
          components: [
            { name: "Production APNs", state: "Degraded", successes_24h: 4, failures_24h: 7, failing_devices: 3 },
            ...fiveHealthyComponents.slice(1),
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Push notifications" });

    // No nested <table> anywhere on the page any more.
    expect(document.querySelector("table")).toBeNull();

    const prodCard = screen.getByText("Production APNs").closest(".cc-record-card");
    expect(prodCard).not.toBeNull();
    const withinProd = within(prodCard as HTMLElement);
    expect(withinProd.getByText(/4 successes \(24h\)/)).toBeInTheDocument();
    expect(withinProd.getByText(/7 failures \(24h\)/)).toBeInTheDocument();
    expect(withinProd.getByText(/3 failing devices/)).toBeInTheDocument();
  });

  it("omits the failing-device count when it is zero", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "All production-relevant push components are healthy.",
          components: fiveHealthyComponents,
        })
      );
    });
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Push notifications" });

    const prodCard = screen.getByText("Production APNs").closest(".cc-record-card");
    expect(within(prodCard as HTMLElement).queryByText(/failing device/)).not.toBeInTheDocument();
  });

  it("presents a sandbox-only degraded component while Push overall remains healthy", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation:
            "5 active web subscriptions. All production-relevant push components are healthy. " +
            "Sandbox APNs has recent failures — visible in the components below, not a production outage.",
          components: [
            { name: "Production APNs", state: "Healthy", successes_24h: 8, failures_24h: 0, failing_devices: 0 },
            { name: "Sandbox APNs", state: "Degraded", successes_24h: 0, failures_24h: 4, failing_devices: 2 },
            ...fiveHealthyComponents.slice(2),
          ],
        })
      );
    });
    render(<HealthPage />);
    const heading = await screen.findByRole("heading", { name: "Push notifications" });
    const pushCard = heading.closest(".cc-card") as HTMLElement;
    const topLevelBadge = pushCard.querySelector(".cc-card-actions");
    expect(topLevelBadge).not.toBeNull();
    expect(within(topLevelBadge as HTMLElement).getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText(/not a production outage/)).toBeInTheDocument();

    const sandboxCard = screen.getByText("Sandbox APNs").closest(".cc-record-card");
    expect(within(sandboxCard as HTMLElement).getByText("Degraded")).toBeInTheDocument();
  });

  it("presents a production failure as a top-level degradation naming the component", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Degraded",
          explanation: "Production APNs is failing in the last 24 hours. See the Push page for details.",
          components: [
            { name: "Production APNs", state: "Degraded", successes_24h: 0, failures_24h: 6, failing_devices: 4 },
            ...fiveHealthyComponents.slice(1),
          ],
        })
      );
    });
    render(<HealthPage />);
    const heading = await screen.findByRole("heading", { name: "Push notifications" });
    const pushCard = heading.closest(".cc-card") as HTMLElement;
    const topLevelBadge = pushCard.querySelector(".cc-card-actions");
    expect(topLevelBadge).not.toBeNull();
    expect(within(topLevelBadge as HTMLElement).getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText(/Production APNs is failing/)).toBeInTheDocument();

    const prodCard = screen.getByText("Production APNs").closest(".cc-record-card");
    expect(within(prodCard as HTMLElement).getByText("Degraded")).toBeInTheDocument();
  });

  it("shows the corrected configured-state copy for a native-only deployment", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "0 active web subscriptions. All production-relevant push components are healthy.",
          components: fiveHealthyComponents,
        })
      );
    });
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Push notifications" });

    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
  });

  it("links View push diagnostics to the existing Push page", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "All production-relevant push components are healthy.",
          components: fiveHealthyComponents,
        })
      );
    });
    render(<HealthPage />);
    await screen.findByRole("heading", { name: "Push notifications" });

    const link = screen.getByRole("link", { name: "View push diagnostics" });
    expect(link).toHaveAttribute("href", "/push");
  });
});
