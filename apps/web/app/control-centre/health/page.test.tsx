import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
  it("renders overall status and per-service checks", async () => {
    render(<HealthPage />);
    expect((await screen.findAllByText("Healthy")).length).toBeGreaterThan(0);
    expect(screen.getByText("Database")).toBeInTheDocument();
    expect(screen.getByText("Email provider")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });

  it("shows the operator action for a degraded service", async () => {
    render(<HealthPage />);
    await screen.findByText("Email provider");
    expect(screen.getByText("Check provider status page.")).toBeInTheDocument();
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

describe("Health — Push notifications component breakdown", () => {
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

  it("renders a row for each push component with its counts", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "All production-relevant push components are healthy.",
          components: [
            { name: "Production APNs", state: "Healthy", successes_24h: 12, failures_24h: 0, failing_devices: 0 },
            { name: "Sandbox APNs", state: "Degraded", successes_24h: 3, failures_24h: 2, failing_devices: 1 },
            { name: "Android FCM", state: "Healthy", successes_24h: 8, failures_24h: 0, failing_devices: 0 },
            { name: "Web Push", state: "Healthy", successes_24h: 5, failures_24h: 0, failing_devices: 0 },
            { name: "Legacy iOS", state: "Warning", successes_24h: 0, failures_24h: 1, failing_devices: 1 },
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByText("Push notifications");

    expect(screen.getByText("Production APNs")).toBeInTheDocument();
    expect(screen.getByText("Sandbox APNs")).toBeInTheDocument();
    expect(screen.getByText("Android FCM")).toBeInTheDocument();
    expect(screen.getByText("Web Push")).toBeInTheDocument();
    expect(screen.getByText("Legacy iOS")).toBeInTheDocument();
  });

  it("shows per-component success/failure/failing-device counts", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Degraded",
          explanation: "Production APNs is failing in the last 24 hours.",
          components: [
            { name: "Production APNs", state: "Degraded", successes_24h: 4, failures_24h: 7, failing_devices: 3 },
            { name: "Sandbox APNs", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Android FCM", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Web Push", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Legacy iOS", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByText("Production APNs");

    const row = screen.getByText("Production APNs").closest("tr");
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("4");
    expect(row!.textContent).toContain("7");
    expect(row!.textContent).toContain("3");
  });

  it("presents a sandbox-only failure without implying a production outage", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation:
            "3 active web subscriptions. All production-relevant push components are healthy. " +
            "Sandbox APNs has recent failures — visible in the components below, not a production outage.",
          components: [
            { name: "Production APNs", state: "Healthy", successes_24h: 5, failures_24h: 0, failing_devices: 0 },
            { name: "Sandbox APNs", state: "Degraded", successes_24h: 0, failures_24h: 4, failing_devices: 2 },
            { name: "Android FCM", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Web Push", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Legacy iOS", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByText("Push notifications");

    expect(screen.getByText(/not a production outage/)).toBeInTheDocument();
    const sandboxRow = screen.getByText("Sandbox APNs").closest("tr");
    expect(sandboxRow!.textContent).toContain("Degraded");
    const topLevelBadges = screen.getAllByText("Healthy");
    expect(topLevelBadges.length).toBeGreaterThan(0);
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
            { name: "Sandbox APNs", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Android FCM", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Web Push", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Legacy iOS", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByText("Push notifications");

    expect(screen.getByText(/Production APNs is failing/)).toBeInTheDocument();
    const prodRow = screen.getByText("Production APNs").closest("tr");
    expect(prodRow!.textContent).toContain("Degraded");
  });

  it("shows the corrected configured-state copy for a native-only deployment", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.resolve(
        pushResponse({
          state: "Healthy",
          explanation: "0 active web subscriptions. All production-relevant push components are healthy.",
          components: [
            { name: "Production APNs", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Sandbox APNs", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Android FCM", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Web Push", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
            { name: "Legacy iOS", state: "Healthy", successes_24h: 0, failures_24h: 0, failing_devices: 0 },
          ],
        })
      );
    });
    render(<HealthPage />);
    await screen.findByText("Push notifications");

    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
  });
});
