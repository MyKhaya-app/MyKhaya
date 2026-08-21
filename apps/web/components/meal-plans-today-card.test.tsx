import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { MealPlanEntry } from "@mykhaya/shared-types";
import { MealPlansTodayCard } from "./meal-plans-today-card";

// Regression coverage for the Home screen's Meals card. It used to be
// "Tonight" and only ever looked at the Dinner slot (meal-plan
// -tonight-card.tsx's `.find((entry) => entry.meal_slot === "dinner")`) —
// a household with, say, Lunch planned but no Dinner saw nothing at all.
// This card now shows every slot that actually has a meal today, in
// Breakfast/Lunch/Dinner order, and hides itself entirely when nothing is
// planned rather than showing an empty state.

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      billingStatus: vi.fn(),
      mealPlanDay: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function entry(overrides: Partial<MealPlanEntry> & { meal_slot: MealPlanEntry["meal_slot"] }): MealPlanEntry {
  return {
    id: `entry-${overrides.meal_slot}`,
    meal_id: null,
    meal_name: null,
    quick_meal_name: "A meal",
    meal_image_url: null,
    is_favourite: false,
    date: "2026-08-21",
    time: null,
    member_ids: [],
    cook_member_id: null,
    makes_leftovers: false,
    created_by: "u1",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function mockDay(entries: MealPlanEntry[]) {
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
    date: "2026-08-21",
    entries,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    member_usage: { count: 1, limit: 1, over_limit: false },
    meals_enabled: true,
    lists_enabled: true,
  });
});

describe("MealPlansTodayCard — slot selection", () => {
  it("shows only Breakfast when that's the only meal planned", async () => {
    mockDay([entry({ meal_slot: "breakfast", quick_meal_name: "Porridge" })]);
    render(<MealPlansTodayCard homeId="home-1" />);

    expect(await screen.findByText("Meals")).toBeInTheDocument();
    expect(screen.getByText(/Breakfast/)).toBeInTheDocument();
    expect(screen.getByText(/Porridge/)).toBeInTheDocument();
    expect(screen.queryByText(/Lunch/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Dinner/)).not.toBeInTheDocument();
  });

  it("shows only Lunch when that's the only meal planned", async () => {
    mockDay([entry({ meal_slot: "lunch", quick_meal_name: "Sandwiches" })]);
    render(<MealPlansTodayCard homeId="home-1" />);

    expect(await screen.findByText("Meals")).toBeInTheDocument();
    expect(screen.getByText(/Lunch/)).toBeInTheDocument();
    expect(screen.getByText(/Sandwiches/)).toBeInTheDocument();
    expect(screen.queryByText(/Breakfast/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Dinner/)).not.toBeInTheDocument();
  });

  it("shows only Dinner when that's the only meal planned, without the word 'Tonight'", async () => {
    mockDay([entry({ meal_slot: "dinner", quick_meal_name: "Pizza Friday" })]);
    render(<MealPlansTodayCard homeId="home-1" />);

    expect(await screen.findByText("Meals")).toBeInTheDocument();
    expect(screen.queryByText(/tonight/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Dinner/)).toBeInTheDocument();
    expect(screen.getByText(/Pizza Friday/)).toBeInTheDocument();
  });

  it("shows Breakfast and Lunch, in that order, when both are planned", async () => {
    mockDay([
      entry({ meal_slot: "lunch", quick_meal_name: "Chicken wraps" }),
      entry({ meal_slot: "breakfast", quick_meal_name: "Overnight oats" }),
    ]);
    render(<MealPlansTodayCard homeId="home-1" />);

    const rows = await screen.findAllByText(/Breakfast|Lunch|Dinner/);
    expect(rows.map((row) => row.textContent)).toEqual(["Breakfast", "Lunch"]);
  });

  it("shows Lunch and Dinner, in that order, when both are planned", async () => {
    mockDay([
      entry({ meal_slot: "dinner", quick_meal_name: "Pizza Friday" }),
      entry({ meal_slot: "lunch", quick_meal_name: "Chicken wraps" }),
    ]);
    render(<MealPlansTodayCard homeId="home-1" />);

    const rows = await screen.findAllByText(/Breakfast|Lunch|Dinner/);
    expect(rows.map((row) => row.textContent)).toEqual(["Lunch", "Dinner"]);
    expect(screen.getByText(/Chicken wraps/)).toBeInTheDocument();
    expect(screen.getByText(/Pizza Friday/)).toBeInTheDocument();
  });

  it("shows all three meals, in Breakfast/Lunch/Dinner order, when all are planned", async () => {
    mockDay([
      entry({ meal_slot: "dinner", quick_meal_name: "Pizza Friday" }),
      entry({ meal_slot: "breakfast", quick_meal_name: "Overnight oats" }),
      entry({ meal_slot: "lunch", quick_meal_name: "Chicken wraps" }),
    ]);
    render(<MealPlansTodayCard homeId="home-1" />);

    const rows = await screen.findAllByText(/Breakfast|Lunch|Dinner/);
    expect(rows.map((row) => row.textContent)).toEqual(["Breakfast", "Lunch", "Dinner"]);
  });

  it("includes the participant count using the existing 'N eating' behaviour", async () => {
    mockDay([
      entry({ meal_slot: "dinner", quick_meal_name: "Pizza Friday", member_ids: ["a", "b", "c"] }),
    ]);
    render(<MealPlansTodayCard homeId="home-1" />);

    expect(await screen.findByText(/3 eating/)).toBeInTheDocument();
  });
});

describe("MealPlansTodayCard — empty/hidden states", () => {
  it("hides the card entirely when nothing is planned today", async () => {
    mockDay([]);
    render(<MealPlansTodayCard homeId="home-1" />);

    await waitFor(() => expect(api.mealPlanDay).toHaveBeenCalled());
    expect(screen.queryByText("Meals")).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing planned/i)).not.toBeInTheDocument();
  });

  it("hides the card when Meal Plans isn't enabled for this Home, without calling mealPlanDay", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      member_usage: { count: 1, limit: 1, over_limit: false },
      meals_enabled: false,
      lists_enabled: false,
    });
    render(<MealPlansTodayCard homeId="home-1" />);

    await waitFor(() => expect(api.billingStatus).toHaveBeenCalled());
    expect(screen.queryByText("Meals")).not.toBeInTheDocument();
    expect(api.mealPlanDay).not.toHaveBeenCalled();
  });
});

describe("MealPlansTodayCard — navigation", () => {
  it("still links 'View meal plan' to /meal-plans", async () => {
    mockDay([entry({ meal_slot: "dinner", quick_meal_name: "Pizza Friday" })]);
    render(<MealPlansTodayCard homeId="home-1" />);

    const link = await screen.findByRole("link", { name: /view meal plan/i });
    expect(link).toHaveAttribute("href", "/meal-plans");
  });
});
