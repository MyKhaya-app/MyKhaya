import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import UsagePage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/usage",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const actor = { id: "op-1", email: "op@mykhaya.app", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" as const };
const report = {
  period: { start: "2026-08-18", end: "2026-09-16", days: 30, timezone: "UTC" },
  overview: { active_users: 4, active_homes: 2, usage_sessions: 5, product_events: 16 },
  engagement: { dau: 2, wau: 3, mau: 4, returning_users: 1, new_users: 3 },
  homes: { active: 2, eligible: 10 },
  trend: [{ date: "2026-09-16", active_users: 2, active_homes: 1 }],
  modules: [{ module: "lists", active_users: 3, event_count: 8, share_of_active_users: 75 }],
  platforms: [{ platform: "web", active_users: 4, usage_sessions: 5, event_count: 16, share_of_global_users: 100 }],
  events: [{ event_name: "app_open", event_count: 4 }],
};

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(report));
});

describe("PCC Usage", () => {
  it("renders production defaults and report sections", async () => {
    render(<UsagePage />);
    expect(await screen.findByRole("heading", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Usage" })).toHaveAttribute("href", "/usage");
    expect(screen.getByText("Active users")).toBeInTheDocument();
    expect(screen.getByText("Engagement")).toBeInTheDocument();
    expect(screen.getByText("Modules")).toBeInTheDocument();
    expect(screen.getByText("Platforms")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/usage/report?days=30&classification=production");
  });

  it("renders a useful no-activity state without divide-by-zero output", async () => {
    get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve({ ...report, overview: { ...report.overview, active_users: 0, product_events: 0 }, trend: [] }));
    render(<UsagePage />);
    expect(await screen.findByText("No qualifying product activity matches these filters.")).toBeInTheDocument();
    expect(screen.queryByText(/NaN|Infinity/)).not.toBeInTheDocument();
  });
});
