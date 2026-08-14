import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import SubscriptionsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/subscriptions",
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

const summary = {
  total_homes: 5,
  free: 3,
  family: 2,
  complimentary: 1,
  complimentary_expired: 0,
  past_due: 0,
  cancelled: 0,
  stripe_total: 1,
  stripe_active_family: 1,
  stripe_monthly: 1,
  stripe_annual: 0,
  stripe_cancelling: 0,
};

const listing = {
  items: [
    {
      id: "home-1",
      name: "Hales Home",
      stored_plan: "family",
      provider: "complimentary",
      status: "active",
      effective_plan: "family",
      effective_status_reason: null,
      complimentary_expires_at: null,
      member_count: 3,
      last_commercial_change: "2026-02-01T00:00:00Z",
    },
  ],
  page: 1,
  page_size: 25,
  total: 1,
};

const webhookHealth = {
  configured: false,
  state: "not_configured",
  reason: null,
  last_event_at: null,
  recent_failure_count: 0,
  recent_events: [],
  recent_failures: [],
};

function mockRoutes() {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/subscriptions/summary") return Promise.resolve(summary);
    if (path === "/subscriptions/webhook-health") return Promise.resolve(webhookHealth);
    if (path.startsWith("/subscriptions?")) return Promise.resolve(listing);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SubscriptionsPage", () => {
  it("renders the summary and the Homes table once loaded", async () => {
    mockRoutes();
    render(<SubscriptionsPage />);
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Effective plan" })).toBeInTheDocument();
    expect(screen.getAllByText("Family").length).toBeGreaterThan(0);
  });

  it("shows the empty state when no Homes match the filters", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      if (path === "/subscriptions/summary") return Promise.resolve(summary);
      if (path === "/subscriptions/webhook-health") return Promise.resolve(webhookHealth);
      if (path.startsWith("/subscriptions?")) return Promise.resolve({ ...listing, items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    render(<SubscriptionsPage />);
    await waitFor(() =>
      expect(screen.getByText("No Homes match these filters.")).toBeInTheDocument(),
    );
  });

  it("shows an error notice when the subscriptions request fails", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.reject(new Error("could not load"));
    });
    render(<SubscriptionsPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
