import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import HomePage from "./page";

// Coverage for the Home screen's "Around the house" Meal Plans shortcut —
// see docs/architecture/meal-plans.md. The shortcut always links to
// /meal-plans (the destination page owns the Family/Free FamilyUpsell gate)
// but is only rendered at all when the module is actually released for this
// Home (mirrors the existing calendarEnabled precedent), and shows a locked
// treatment rather than disappearing when the Home is on the Free plan.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/home",
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
      me: vi.fn(),
      birthdays: vi.fn(),
      billingStatus: vi.fn(),
      featureMatrix: vi.fn(),
      members: vi.fn(),
      homeSummary: vi.fn(),
      listEvents: vi.fn(),
      routines: vi.fn(),
      completeRoutine: vi.fn(),
      mealPlanDay: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function billing(overrides: Record<string, unknown> = {}) {
  return {
    member_usage: { count: 1, limit: 1, over_limit: false },
    meals_enabled: false,
    lists_enabled: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan" });
  (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.completeRoutine as ReturnType<typeof vi.fn>).mockResolvedValue({});
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({ date: "2026-08-20", entries: [] });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [
      { feature: "calendar", enabled: false },
      { feature: "meals", enabled: true },
      { feature: "shopping", enabled: true },
    ],
  });
});

describe("Home — Meal plans shortcut", () => {
  it("links to Meal Plans with no lock treatment on a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /meal plans/i });
    expect(link).toHaveAttribute("href", "/meal-plans");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("shows the locked treatment but still links through on a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: false }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /meal plans/i });
    expect(link).toHaveAttribute("href", "/meal-plans");
    expect(link.className).toMatch(/quick-action-locked/);
  });

  it("hides the shortcut entirely when the module isn't released for this Home", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
      ],
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));

    render(<HomePage />);

    await screen.findByText(/around the house/i);
    expect(screen.queryByRole("link", { name: /meal plans/i })).not.toBeInTheDocument();
  });
});

describe("Home — Lists shortcut", () => {
  it("links to Lists with no lock treatment on a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: true }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^lists$/i });
    expect(link).toHaveAttribute("href", "/lists");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("shows the locked treatment but still links through on a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: false }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^lists$/i });
    expect(link).toHaveAttribute("href", "/lists");
    expect(link.className).toMatch(/quick-action-locked/);
  });

  it("hides the shortcut entirely when the module isn't released for this Home", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "shopping", enabled: false },
      ],
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: true }));

    render(<HomePage />);

    await screen.findByText(/around the house/i);
    expect(screen.queryByRole("link", { name: /^lists$/i })).not.toBeInTheDocument();
  });
});

describe("Home — household routines", () => {
  it("shows an outstanding routine and completes its current occurrence", async () => {
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "routine-1",
          title: "Put green bin out",
          description: null,
          scope: "household",
          owner_user_id: null,
          interval_weeks: 1,
          repeat_unit: "weekly",
          week_anchor_date: tomorrow,
          reminder_timing: "evening_before",
          is_critical: false,
          pinned: false,
          enabled: true,
          start_date: tomorrow,
          end_date: null,
          member_ids: ["u1"],
          next_occurrence_date: tomorrow,
          completed_today: false,
          home_occurrence_date: tomorrow,
          home_completed_at: null,
          home_completed_by_user_id: null,
          home_completed_by_display_name: null,
          created_by: "u1",
          updated_at: new Date().toISOString(),
        },
      ],
    });

    render(<HomePage />);

    expect(await screen.findByText("Put green bin out")).toBeInTheDocument();
    expect(screen.getByText(/Tomorrow · Household/)).toBeInTheDocument();
    screen.getByRole("button", { name: /complete put green bin out/i }).click();
    expect(await screen.findByText(/Done by Megan/)).toBeInTheDocument();
    expect(api.completeRoutine).toHaveBeenCalledWith("home-1", "routine-1", tomorrow);
  });
});
