import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Member } from "@mykhaya/shared-types";
import MealPlansPage from "./page";

// Locked-state and basic-render coverage for the Meal Plans module — see
// docs/architecture/meal-plans.md. Mirrors the pattern already used by
// app/settings/routines/page.test.tsx for Free-vs-Family locked states.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/meal-plans",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      billingStatus: vi.fn(),
      members: vi.fn(),
      mealPlanDay: vi.fn(),
      meals: vi.fn(),
      me: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function member(): Member {
  return {
    membership_id: "m1",
    user_id: "u1",
    display_name: "Megan",
    email: null,
    role: "member",
    relationship: "home_admin",
    permission_profile: "home_admin",
    permission_overrides: {},
    shared_resources: [],
    colour: null,
    avatar_version: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([member()]);
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({ date: "2026-08-16", entries: [] });
  (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
});

describe("Meal Plans — Free plan locked state", () => {
  it("shows the Family upsell and no planner content for a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: false,
    });

    render(<MealPlansPage />);

    expect(await screen.findByText(/view family plan/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Meals" })).not.toBeInTheDocument();
  });
});

describe("Meal Plans — Family plan access", () => {
  it("renders the planner tabs and today's day view for a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);

    expect(await screen.findByRole("tab", { name: "Plan" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Meals" })).toBeInTheDocument();
    expect(screen.getAllByText("Breakfast").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Lunch").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dinner").length).toBeGreaterThan(0);
  });
});
