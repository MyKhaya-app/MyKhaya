import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import NotificationsOverviewPage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/notifications",
  useRouter: () => stableRouter,
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

const templates = [
  { template_type: "a", module: "calendar", channel: "in_app", is_override: true, enabled: true, security_critical: false },
  { template_type: "b", module: "calendar", channel: "in_app", is_override: false, enabled: true, security_critical: false },
  { template_type: "c", module: "security", channel: "email", is_override: false, enabled: false, security_critical: true },
];

const health = {
  overall: "degraded" as const,
  smtp: { configured: true, status: "ok" },
  push: { configured: false, status: "not set up" },
  failures_today: 3,
  deliveries_today: 42,
};

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/notification-templates") return Promise.resolve(overrides.templates ?? templates);
    if (path === "/communications/health") return Promise.resolve(overrides.health ?? health);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NotificationsOverviewPage", () => {
  it("derives counts from the real registered templates rather than inventing statistics", async () => {
    mockRoutes();
    render(<NotificationsOverviewPage />);
    await waitFor(() => expect(screen.getByText("Registered types")).toBeInTheDocument());
    const grid = screen.getByText("Registered types").closest("section")!;
    expect(grid).toHaveTextContent("3");
    expect(screen.getByText("Customised")).toBeInTheDocument();
    expect(screen.getByText("Using built-in default")).toBeInTheDocument();
  });

  it("renders channel health from the shared communications endpoint", async () => {
    mockRoutes();
    render(<NotificationsOverviewPage />);
    await waitFor(() => expect(screen.getByText("Channel health")).toBeInTheDocument());
    expect(screen.getByText("Email configured")).toBeInTheDocument();
    expect(screen.getByText("Push not configured")).toBeInTheDocument();
  });

  it("surfaces a failure-count banner linking to delivery logs when failures exist", async () => {
    mockRoutes();
    render(<NotificationsOverviewPage />);
    const link = await screen.findByRole("link", { name: "view delivery logs" });
    expect(link).toHaveAttribute("href", "/notifications/delivery-logs");
  });

  it("does not show a failure banner when there are no failures today", async () => {
    mockRoutes({ health: { ...health, failures_today: 0 } });
    render(<NotificationsOverviewPage />);
    await waitFor(() => expect(screen.getByText("Channel health")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "view delivery logs" })).not.toBeInTheDocument();
  });

  it("still renders template stats when the health endpoint is unavailable", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      if (path === "/notification-templates") return Promise.resolve(templates);
      if (path === "/communications/health") return Promise.reject(new Error("down"));
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    render(<NotificationsOverviewPage />);
    await waitFor(() => expect(screen.getByText("Registered types")).toBeInTheDocument());
    expect(screen.queryByText("Channel health")).not.toBeInTheDocument();
  });

  it("links shortcuts to the Templates, Test Centre and Delivery Logs pages", async () => {
    mockRoutes();
    render(<NotificationsOverviewPage />);
    await waitFor(() => expect(screen.getByText("Shortcuts")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Browse templates" })).toHaveAttribute(
      "href",
      "/notifications/templates",
    );
    expect(screen.getByRole("link", { name: "Send a test notification" })).toHaveAttribute(
      "href",
      "/notifications/test-centre",
    );
  });
});
