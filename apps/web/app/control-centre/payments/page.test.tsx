import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PaymentsPage from "./page";
import type { StripeConfiguration } from "@/components/platform-types";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/payments",
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
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

const emptyModeSettings = {
  publishable_key: null,
  secret_key_configured: false,
  secret_key_last4: null,
  webhook_secret_configured: false,
  webhook_secret_last4: null,
  family_monthly_price_id: null,
  family_annual_price_id: null,
};

const unconfigured: StripeConfiguration = {
  configured: false,
  enabled: false,
  acquisition_enabled: false,
  mode: "test" as const,
  source: "unconfigured" as const,
  incomplete_reason: null,
  editable: true,
  updated_at: null,
  test: emptyModeSettings,
  live: emptyModeSettings,
  webhook: {
    configured: false,
    state: "not_configured",
    reason: null,
    last_event_at: null,
    recent_failure_count: 0,
    endpoint_url: "/billing/stripe/webhook",
  },
};

const configuredTest: StripeConfiguration = {
  ...unconfigured,
  configured: true,
  enabled: true,
  acquisition_enabled: true,
  source: "database" as const,
  editable: true,
  test: {
    ...emptyModeSettings,
    publishable_key: "pk_test_abc123",
    secret_key_configured: true,
    secret_key_last4: "c123",
    webhook_secret_configured: true,
    webhook_secret_last4: "3123",
    family_monthly_price_id: "price_month_test",
    family_annual_price_id: "price_year_test",
  },
};

function mockRoutes(config = unconfigured) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/payments/stripe") return Promise.resolve(config);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PaymentsPage", () => {
  it("renders the unconfigured state", async () => {
    mockRoutes(unconfigured);
    render(<PaymentsPage />);
    await waitFor(() => expect(screen.getByText("Disabled")).toBeInTheDocument());
    expect(screen.getAllByText(/not.configured/i).length).toBeGreaterThan(0);
  });

  it("never renders a real secret value — only masked last-4 metadata", async () => {
    mockRoutes(configuredTest);
    render(<PaymentsPage />);
    await waitFor(() => expect(screen.getAllByText("Enabled").length).toBeGreaterThan(0));
    expect(document.body.textContent).not.toContain("sk_test_abc123");
    expect(document.body.textContent).not.toContain("whsec");
    const secretInputs = screen.getAllByPlaceholderText(/••••••••••••/);
    expect(secretInputs.length).toBeGreaterThan(0);
  });

  it("shows a Live-mode warning notice when Live is selected", async () => {
    mockRoutes({ ...configuredTest, mode: "live" });
    render(<PaymentsPage />);
    await waitFor(() => expect(screen.getAllByText("Live").length).toBeGreaterThan(0));
    expect(
      screen.getByText(/Selecting Live mode makes real Stripe billing active/i),
    ).toBeInTheDocument();
  });

  it("disables the form when environment-managed", async () => {
    mockRoutes({ ...configuredTest, source: "environment", editable: false });
    render(<PaymentsPage />);
    await waitFor(() =>
      expect(screen.getByText(/managed by the deployment environment/i)).toBeInTheDocument(),
    );
  });

  it("shows an error notice when the request fails", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.reject(new Error("could not load"));
    });
    render(<PaymentsPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
