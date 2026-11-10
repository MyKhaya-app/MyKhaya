import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type {
  BillingStatus,
  FamilyPricing,
  PlanComparison,
} from "@mykhaya/shared-types";
import PlanAndBillingSettings from "./page";

const mockRouter = { push: vi.fn(), replace: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/settings-page", () => ({
  SettingsPage: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({ activeHomeId: "home-1", loading: false }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      billingStatus: vi.fn(),
      familyPricing: vi.fn(),
      planComparison: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function billingStatus(): BillingStatus {
  return {
    effective_plan: "family",
    stored_plan: "family",
    provider: "stripe",
    status: "active",
    billing_interval: "month",
    price: { formatted_amount: "£3.99" },
    can_manage_billing: true,
    has_stripe_customer: true,
    stripe_billing_available: true,
    calendar_usage: { count: 1, limit: null, over_limit: false },
    member_usage: { count: 1, limit: null, over_limit: false },
  } as unknown as BillingStatus;
}

function pricing(): FamilyPricing {
  return {
    options: [{ interval: "month", formatted_amount: "£3.99" }],
    ultimate_options: [{ interval: "month", formatted_amount: "£5.99" }],
    acquisition_enabled: true,
    ultimate_acquisition_enabled: true,
  } as unknown as FamilyPricing;
}

function comparison(): PlanComparison {
  return {
    rows: [
      {
        key: "home.max_members",
        label: "People",
        free_display: "1 person",
        family_display: "Household",
        ultimate_display: "Household",
      },
    ],
  } as unknown as PlanComparison;
}

describe("Plan & Billing responsive structure", () => {
  beforeEach(() => {
    vi.mocked(api.billingStatus).mockResolvedValue(billingStatus());
    vi.mocked(api.familyPricing).mockResolvedValue(pricing());
    vi.mocked(api.planComparison).mockResolvedValue(comparison());
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("keeps all plan actions and exposes mobile comparison labels from one data source", async () => {
    render(<PlanAndBillingSettings />);

    const compareHeading = await screen.findAllByRole("heading", {
      name: "Compare plans",
    });
    const plansSection = compareHeading[0]!.closest("section");
    const comparisonSection = compareHeading[1]!.closest("section");
    expect(plansSection).not.toBeNull();
    expect(comparisonSection).not.toBeNull();
    const compareView = within(comparisonSection!);
    expect(plansSection!.querySelectorAll(".plan-option-card")).toHaveLength(3);
    expect(
      screen.getByRole("button", { name: "Manage billing" }),
    ).toBeInTheDocument();
    expect(compareView.getAllByText("Free")).toHaveLength(2);
    expect(compareView.getAllByText("Family")).toHaveLength(2);
    expect(compareView.getAllByText("Ultimate")).toHaveLength(2);
    expect(compareView.getByText("People")).toBeInTheDocument();
    expect(compareView.getByText("1 person")).toBeInTheDocument();
    expect(compareView.getAllByText("Household")).toHaveLength(2);
  });
});
