import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      featureMatrix: vi.fn(),
      mealPlanDay: vi.fn(),
      mealPlanWeek: vi.fn(),
      meals: vi.fn(),
      meal: vi.fn(),
      recentMeals: vi.fn(),
      me: vi.fn(),
      createMealPlanEntry: vi.fn(),
      lists: vi.fn(),
      addIngredientsToList: vi.fn(),
      copyMealPlanWeek: vi.fn(),
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
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "meals", enabled: true }],
  });
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({ date: "2026-08-16", entries: [] });
  (api.mealPlanWeek as ReturnType<typeof vi.fn>).mockResolvedValue({ days: [] });
  (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.recentMeals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.createMealPlanEntry as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "entry-1",
    date: "2026-08-16",
    meal_slot: "breakfast",
  });
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

  it("switches to the Week view via the Day/Week control and fetches week data", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ meals_enabled: true });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });

    await user.click(screen.getByRole("tab", { name: "Week" }));

    expect(api.mealPlanWeek).toHaveBeenCalled();
  });
});

describe("Meal Plans — Add meal sheet", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ meals_enabled: true });
  });

  async function openBreakfastAddSheet() {
    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });
    const breakfastSection = screen.getByText("Breakfast").closest(".meal-slot-section");
    if (!breakfastSection) throw new Error("Breakfast section not found");
    await user.click(within(breakfastSection as HTMLElement).getByRole("button", { name: /add/i }));
    return user;
  }

  it("shows the slot-appropriate placeholder and keeps Date in its own field", async () => {
    await openBreakfastAddSheet();

    expect(await screen.findByPlaceholderText(/overnight oats/i)).toBeInTheDocument();

    // Date is its own label/input pair, distinct from the Meal-slot and Time
    // controls — never a shared three-column row.
    const dateLabel = screen.getByText("Date").closest("label");
    expect(dateLabel?.querySelector('input[type="date"]')).toBeTruthy();
    expect(dateLabel?.querySelector("select")).toBeNull();

    expect(screen.getByLabelText(/time \(optional\)/i)).toHaveAttribute("type", "time");
  });

  it("submits a quick meal for the selected slot", async () => {
    const user = await openBreakfastAddSheet();
    const nameInput = await screen.findByPlaceholderText(/overnight oats/i);
    await user.type(nameInput, "Porridge");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createMealPlanEntry).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ quick_meal_name: "Porridge", meal_slot: "breakfast" }),
    );
  });
});

describe("Meal Plans — feature-gate consistency", () => {
  it("shows a calm message instead of the interactive planner when the module isn't released", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ meals_enabled: true });
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [{ feature: "meals", enabled: false }],
    });

    render(<MealPlansPage />);

    expect(await screen.findByText(/isn't available for this home yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Plan" })).not.toBeInTheDocument();
    // Never the raw backend "Not found" string this was built to replace.
    expect(screen.queryByText(/^not found$/i)).not.toBeInTheDocument();
  });
});

describe("Meal Plans — Meals library", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ meals_enabled: true });
  });

  function meal(overrides: Record<string, unknown> = {}) {
    return {
      id: "meal-1",
      name: "Lasagne",
      description: null,
      image_url: null,
      meal_type: "dinner",
      prep_minutes: 20,
      cook_minutes: 45,
      servings: 6,
      is_favourite: false,
      tags: [],
      ingredient_count: 2,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      ...overrides,
    };
  }

  it("shows the empty state with a call to action when there are no saved meals", async () => {
    (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Meals" }));

    expect(await screen.findByText(/no saved meals yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add your first meal/i })).toBeInTheDocument();
  });

  it("adds a meal's ingredients to a chosen list, handling the confirm-duplicates step", async () => {
    (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [meal()] });
    (api.meal as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...meal(),
      instructions: null,
      source_url: null,
      created_by: "u1",
      ingredients: [
        { id: "ing-1", position: 0, text: "beef mince", quantity: "500", unit: "g" },
        { id: "ing-2", position: 1, text: "onion", quantity: "1", unit: null },
      ],
    });
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "list-1", name: "Groceries", item_count: 1, created_by: "u1", created_at: "", updated_at: "" }],
    });
    (api.addIngredientsToList as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      requires_confirmation: true,
      added_count: 0,
      duplicate_count: 1,
      duplicate_texts: ["500 g beef mince"],
      list_id: "list-1",
    });
    (api.addIngredientsToList as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      requires_confirmation: false,
      added_count: 1,
      duplicate_count: 1,
      duplicate_texts: ["500 g beef mince"],
      list_id: "list-1",
    });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Meals" }));
    await user.click(await screen.findByRole("button", { name: /more actions for lasagne/i }));
    await user.click(await screen.findByRole("button", { name: /add ingredients to list/i }));

    await screen.findByText("beef mince", { exact: false });
    await user.click(screen.getByRole("button", { name: /add 2 items/i }));

    expect(await screen.findByText(/already on groceries/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /add remaining/i }));

    expect(await screen.findByText(/added 1 item to groceries/i)).toBeInTheDocument();
    expect(api.addIngredientsToList).toHaveBeenCalledTimes(2);
    expect(api.addIngredientsToList).toHaveBeenLastCalledWith(
      "home-1",
      "meal-1",
      expect.objectContaining({ list_id: "list-1", confirm: true }),
    );
  });
});

describe("Meal Plans — Copy previous week", () => {
  it("previews then commits a week copy from the Week view", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ meals_enabled: true });
    (api.copyMealPlanWeek as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      copied_count: 3,
      skipped_count: 1,
    });
    (api.copyMealPlanWeek as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      copied_count: 3,
      skipped_count: 1,
    });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });
    await user.click(screen.getByRole("tab", { name: "Week" }));
    await user.click(await screen.findByRole("button", { name: /copy previous week/i }));

    expect(await screen.findByText(/this will copy 3 planned meals/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^copy week$/i }));

    expect(await screen.findByText(/3 meals copied/i)).toBeInTheDocument();
    expect(screen.getByText(/1 existing meal left unchanged/i)).toBeInTheDocument();
    expect(api.copyMealPlanWeek).toHaveBeenCalledTimes(2);
  });
});
