import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PlatformOverview from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

const overview = {
  users: { total: 10, verified: 9, unverified: 1, active: 8, suspended: 2 },
  homes: { total: 5, active: 4, suspended: 1 },
  metrics: { users: 10, homes: 5, active_sessions: 3, failed_jobs: 0 },
  security: {
    failed_logins_24h: 0,
    locked_accounts: 0,
    active_administrator_sessions: 2,
    administrators_with_mfa: 2,
    active_administrators: 2,
  },
  operations: { queue_depth: 0 },
  status: { state: "Healthy", checked_at: "2026-08-14T00:00:00Z" },
  health: [{ service: "API", state: "healthy" }],
  actions: [],
  recent_activity: [],
  deployment: {},
};

beforeEach(() => {
  get.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PlatformOverview", () => {
  it("shows a loading state before data arrives", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : new Promise(() => {}),
    );
    render(<PlatformOverview />);
    expect(screen.getByText("Loading platform state…")).toBeInTheDocument();
    // Let PlatformShell's own /auth/me resolution settle before the test ends,
    // so it doesn't log an act() warning against the next test.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("renders core metrics once loaded", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(overview),
    );
    render(<PlatformOverview />);
    await waitFor(() => expect(screen.getByText("Healthy")).toBeInTheDocument());
    expect(screen.getByRole("heading", { level: 3, name: "Users" })).toBeInTheDocument();
    expect(screen.getByText("Failed jobs")).toBeInTheDocument();
  });

  it("shows an error notice when the overview request fails", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.reject(new Error("network down")),
    );
    render(<PlatformOverview />);
    expect(await screen.findByRole("alert")).toHaveTextContent("network down");
  });
});
