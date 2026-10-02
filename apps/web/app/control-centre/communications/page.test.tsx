import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import CommunicationsHealthPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/communications",
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

const health = {
  overall: "degraded" as const,
  worker: { status: "running" as const, last_heartbeat: "2026-09-07T09:00:00Z", detail: "Processing normally." },
  scheduler: { status: "stale" as const, last_heartbeat: "2026-09-07T08:00:00Z", detail: "No tick in the last 5 minutes." },
  smtp: { configured: true, status: "connected" as const },
  push: { configured: false, status: "not_configured" as const },
  queue_depth: 3,
  queue_status: "warning" as const,
  queue_reason: "3 events awaiting delivery.",
  average_latency_seconds: 1.2,
  deliveries_today: 42,
  failures_today: 1,
  retries_today: 2,
};

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/communications/health") return Promise.resolve(overrides.health ?? health);
    if (path === "/auth/me") return Promise.resolve({ email: "op@mykhaya.app" });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CommunicationsHealthPage", () => {
  it("renders the overall status and per-service state", async () => {
    mockRoutes();
    render(<CommunicationsHealthPage />);
    expect(await screen.findByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("Processing normally.")).toBeInTheDocument();
    expect(screen.getByText("No tick in the last 5 minutes.")).toBeInTheDocument();
  });

  it("shows transport configuration state without exposing secrets", async () => {
    mockRoutes();
    render(<CommunicationsHealthPage />);
    await screen.findByText("Degraded");
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toMatch(/password|api[_-]?key|-----begin/);
  });

  it("shows today's delivery figures", async () => {
    mockRoutes();
    render(<CommunicationsHealthPage />);
    await screen.findByText("Degraded");
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("1.2s")).toBeInTheDocument();
  });

  it("shows the API's safe error message when the health request fails", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me"
        ? Promise.resolve({ email: "op@mykhaya.app" })
        : Promise.reject(new ApiError(503, "Health endpoint unreachable")),
    );
    render(<CommunicationsHealthPage />);
    expect(await screen.findByText("Health endpoint unreachable")).toBeInTheDocument();
  });

  it("falls back to a generic message for a non-API failure, without leaking internals", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve({ email: "op@mykhaya.app" }) : Promise.reject(new TypeError("fetch failed")),
    );
    render(<CommunicationsHealthPage />);
    expect(await screen.findByText("Could not load communications health.")).toBeInTheDocument();
    expect(screen.queryByText(/fetch failed/)).not.toBeInTheDocument();
  });

  it("refreshes automatically on a 30-second interval", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    mockRoutes();
    render(<CommunicationsHealthPage />);
    await screen.findByText("Degraded");
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 30_000);
  });
});
