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
