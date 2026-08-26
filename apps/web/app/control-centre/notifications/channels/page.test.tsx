import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import NotificationChannelsPage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/notifications/channels",
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

const health = {
  overall: "healthy" as const,
  smtp: { configured: true, status: "SMTP relay reachable" },
  push: { configured: false, status: "No VAPID keys configured" },
  deliveries_today: 12,
  failures_today: 0,
};

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
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

describe("NotificationChannelsPage", () => {
  it("renders all four channels with their configured/unconfigured state", async () => {
    mockRoutes();
    render(<NotificationChannelsPage />);
    await waitFor(() => expect(screen.getByText(/SMTP relay reachable/)).toBeInTheDocument());

    const rows = screen.getAllByRole("row");
    const emailRow = rows.find((row) => row.textContent?.includes("Email"))!;
    expect(emailRow.textContent).toContain("Configured");

    const pushRow = rows.find((row) => row.textContent?.includes("Push"))!;
    expect(pushRow.textContent).toContain("Not configured");
    expect(pushRow.textContent).toContain("No VAPID keys configured");

    expect(screen.getByText("In-app")).toBeInTheDocument();
    expect(screen.getByText("Daily briefing")).toBeInTheDocument();
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("links out to existing config pages instead of duplicating provider settings", async () => {
    mockRoutes();
    render(<NotificationChannelsPage />);
    await waitFor(() => expect(screen.getByText(/SMTP relay reachable/)).toBeInTheDocument());
    const table = screen.getByRole("table");
    expect(within(table).getByRole("link", { name: "Email" })).toHaveAttribute(
      "href",
      "/mail",
    );
    expect(within(table).getByRole("link", { name: "Push" })).toHaveAttribute(
      "href",
      "/push",
    );
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("never renders anything resembling a secret, key or token value", async () => {
    mockRoutes();
    render(<NotificationChannelsPage />);
    await waitFor(() => expect(screen.getByText(/SMTP relay reachable/)).toBeInTheDocument());
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/sk_[a-z0-9]/i);
    expect(text).not.toMatch(/-----BEGIN/);
    expect(text).not.toMatch(/api[_-]?key/i);
    expect(text).not.toMatch(/password/i);
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("shows today's delivery and failure counts, with a link to logs when failures exist", async () => {
    mockRoutes({ health: { ...health, failures_today: 2 } });
    render(<NotificationChannelsPage />);
    await waitFor(() => expect(screen.getByText("Today")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "delivery logs" })).toHaveAttribute(
      "href",
      "/notifications/delivery-logs",
    );
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("shows a loading state before health data arrives", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : new Promise(() => {}),
    );
    render(<NotificationChannelsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("shows an error notice when the health request fails", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.reject(new Error("unreachable")),
    );
    render(<NotificationChannelsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("unreachable");
  });
});
