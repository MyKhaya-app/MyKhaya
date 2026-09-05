import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
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

function firePointerEvent(
  element: Element,
  type: "pointerdown" | "pointermove" | "pointerup",
  init: {
    pointerId: number;
    pointerType: string;
    clientX: number;
    clientY: number;
  },
) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, init);
  fireEvent(element, event);
}

function member(overrides: Partial<Member> = {}): Member {
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
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([member()]);
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "meals", enabled: true }],
  });
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
    date: "2026-08-16",
    entries: [],
  });
  (api.mealPlanWeek as ReturnType<typeof vi.fn>).mockResolvedValue({
    days: [],
  });
  (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.recentMeals as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [],
  });
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
    expect(
      screen.queryByRole("tab", { name: "Meals" }),
    ).not.toBeInTheDocument();
  });
});

describe("Meal Plans — Family plan access", () => {
  it("renders the planner tabs and today's day view for a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);

    expect(
      await screen.findByRole("tab", { name: "Plan" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Meals" })).toBeInTheDocument();
    expect(screen.getAllByText("Breakfast").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Lunch").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dinner").length).toBeGreaterThan(0);
  });

  it("removes the This Week weekday selector, the View week link and the Shopping List shortcut from this screen", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });

    expect(screen.queryByText("This Week")).not.toBeInTheDocument();
    expect(screen.queryByText(/view week/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/shopping list/i)).not.toBeInTheDocument();
    expect(document.querySelector(".week-strip")).not.toBeInTheDocument();
    // No leftover empty gap/container reserved for the removed section.
    expect(document.querySelectorAll(".week-strip-day").length).toBe(0);
  });

  it("shows multiple real entries for the same slot as individually-tappable lines, each with its own real content", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
      date: "2026-09-05",
      entries: [
        {
          id: "entry-a",
          date: "2026-09-05",
          meal_slot: "lunch",
          meal_name: "Leftover pasta",
          quick_meal_name: null,
          meal_image_url: null,
          time: "12:00:00",
          member_ids: ["u1"],
          cook_member_id: null,
          makes_leftovers: false,
          is_favourite: false,
        },
        {
          id: "entry-b",
          date: "2026-09-05",
          meal_slot: "lunch",
          meal_name: "School lunch",
          quick_meal_name: null,
          meal_image_url: null,
          time: "12:15:00",
          member_ids: ["u2"],
          cook_member_id: null,
          makes_leftovers: false,
          is_favourite: false,
        },
      ],
    });

    render(<MealPlansPage />);
    const lunchCard = (await screen.findByText("Leftover pasta")).closest(".mealplan-slot-card") as HTMLElement;
    expect(within(lunchCard).getByText("School lunch")).toBeInTheDocument();
    expect(within(lunchCard).getAllByRole("button").length).toBeGreaterThanOrEqual(2);
    expect(within(lunchCard).getByRole("button", { name: /add another/i })).toBeInTheDocument();
  });

  it("uses the shared .module-page compact-spacing standard, not a bespoke top-offset or the pre-auth .standard-page top inset alone", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    const { container } = render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });

    const main = container.querySelector("main");
    expect(main).toHaveClass("standard-page");
    expect(main).toHaveClass("module-page");
    // A page-local class asserting its own top offset (the pattern this
    // standard replaces) would be a regression back to chasing this issue
    // module by module — Meal Plans must rely on the shared class only.
    expect(main?.className).not.toMatch(/meal-plans-top|meal-plans-hero-offset/);
  });

  it("renders the hero subtitle and the 'Good food, happier days' artwork as a real image asset", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });

    expect(
      screen.getByText("Plan, cook and enjoy mealtimes together."),
    ).toBeInTheDocument();
    const art = screen.getByAltText("Good food, happier days");
    expect(art.tagName).toBe("IMG");
    expect(art).toHaveAttribute(
      "src",
      expect.stringContaining("/images/meal-plans-good-food.png"),
    );
  });

  it("gives the toolbar its own Meal Plans-only layout wrapper, not the shared Calendar toolbar structure", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    const { container } = render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });

    const toolbar = container.querySelector(".meal-plans-toolbar");
    expect(toolbar).toBeInTheDocument();
    // Calendar's own toolbar classes must never appear on this page — the
    // date-nav/Day-Week row is a page-local layout, not a reuse of
    // .calendar-toolbar-compact/.calendar-month-row.
    expect(container.querySelector(".calendar-toolbar-compact")).not.toBeInTheDocument();
    expect(container.querySelector(".calendar-month-row")).not.toBeInTheDocument();

    const dateNav = toolbar?.querySelector(".meal-plans-date-nav");
    const toolbarRight = toolbar?.querySelector(".meal-plans-toolbar-right");
    expect(dateNav).toBeInTheDocument();
    expect(toolbarRight).toBeInTheDocument();
    // Both groups are children of the same single toolbar row.
    expect(dateNav?.parentElement).toBe(toolbar);
    expect(toolbarRight?.parentElement).toBe(toolbar);

    expect(
      within(dateNav as HTMLElement).getByRole("button", { name: /previous day/i }),
    ).toBeInTheDocument();
    expect(
      within(dateNav as HTMLElement).getByRole("button", { name: /next day/i }),
    ).toBeInTheDocument();
    expect(
      within(toolbarRight as HTMLElement).getByRole("tab", { name: "Day" }),
    ).toBeInTheDocument();
    expect(
      within(toolbarRight as HTMLElement).getByRole("tab", { name: "Week" }),
    ).toBeInTheDocument();
  });

  it("shows a real icon and a compact empty state for each meal slot with nothing planned, under a Today's Plan heading", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });

    expect(screen.getByRole("heading", { name: "Today’s Plan" })).toBeInTheDocument();

    const breakfastSection = screen
      .getByText("Breakfast")
      .closest(".mealplan-slot-card") as HTMLElement;
    expect(within(breakfastSection).getByText("Nothing planned yet")).toBeInTheDocument();
    expect(breakfastSection.querySelector(".mealplan-slot-icon")).toHaveAttribute(
      "src",
      expect.stringContaining("/images/meal-plans-breakfast.png"),
    );

    const lunchSection = screen.getByText("Lunch").closest(".mealplan-slot-card") as HTMLElement;
    expect(within(lunchSection).getByText("Nothing planned yet")).toBeInTheDocument();

    const dinnerSection = screen.getByText("Dinner").closest(".mealplan-slot-card") as HTMLElement;
    expect(within(dinnerSection).getByText("Nothing planned yet")).toBeInTheDocument();

    // No Snacks slot is ever rendered on this screen.
    expect(screen.queryByText("Snack")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Snacks?$/)).not.toBeInTheDocument();
  });

  it("switches to the Week view via the Day/Week control and fetches week data", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });

    await user.click(screen.getByRole("tab", { name: "Week" }));

    expect(api.mealPlanWeek).toHaveBeenCalled();
  });

  it("handles left and right swipes on the rendered Day content surface", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });
    const surface = document.querySelector<HTMLElement>(
      ".meal-day-swipe-surface",
    );
    expect(surface).not.toBeNull();

    firePointerEvent(surface!, "pointerdown", {
      pointerId: 1,
      pointerType: "touch",
      clientX: 200,
      clientY: 200,
    });
    firePointerEvent(surface!, "pointermove", {
      pointerId: 1,
      pointerType: "touch",
      clientX: 100,
      clientY: 200,
    });
    firePointerEvent(surface!, "pointerup", {
      pointerId: 1,
      pointerType: "touch",
      clientX: 100,
      clientY: 200,
    });
    firePointerEvent(surface!, "pointerdown", {
      pointerId: 2,
      pointerType: "touch",
      clientX: 100,
      clientY: 200,
    });
    firePointerEvent(surface!, "pointermove", {
      pointerId: 2,
      pointerType: "touch",
      clientX: 200,
      clientY: 200,
    });
    firePointerEvent(surface!, "pointerup", {
      pointerId: 2,
      pointerType: "touch",
      clientX: 200,
      clientY: 200,
    });

    await vi.waitFor(() => expect(api.mealPlanDay).toHaveBeenCalledTimes(3));
    expect(
      (api.mealPlanDay as ReturnType<typeof vi.fn>).mock.calls[1]![1],
    ).not.toBe((api.mealPlanDay as ReturnType<typeof vi.fn>).mock.calls[0]![1]);
    expect(
      (api.mealPlanDay as ReturnType<typeof vi.fn>).mock.calls[2]![1],
    ).toBe((api.mealPlanDay as ReturnType<typeof vi.fn>).mock.calls[0]![1]);
  });

  it("preserves vertical scrolling and ignores short or vertical-dominant gestures", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    render(<MealPlansPage />);
    await screen.findByRole("tab", { name: "Plan" });
    const surface = document.querySelector<HTMLElement>(
      ".meal-day-swipe-surface",
    )!;

    const swipe = (endX: number, endY: number, pointerId: number) => {
      firePointerEvent(surface, "pointerdown", {
        pointerId,
        pointerType: "touch",
        clientX: 200,
        clientY: 200,
      });
      firePointerEvent(surface, "pointermove", {
        pointerId,
        pointerType: "touch",
        clientX: endX,
        clientY: endY,
      });
      firePointerEvent(surface, "pointerup", {
        pointerId,
        pointerType: "touch",
        clientX: endX,
        clientY: endY,
      });
    };
    swipe(210, 205, 3); // short
    swipe(100, 320, 4); // vertical dominant
    swipe(150, 300, 5); // diagonal vertical dominant

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.mealPlanDay).toHaveBeenCalledTimes(1);
  });

  it("does not mount the Day gesture surface in Week mode", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });
    await user.click(screen.getByRole("tab", { name: "Week" }));
    expect(document.querySelector(".meal-day-swipe-surface")).toBeNull();
  });

  it("keeps a long Dinner title in a shrinkable text column beside participants", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
      date: "2026-08-29",
      entries: [
        {
          id: "entry-dinner",
          date: "2026-08-29",
          meal_slot: "dinner",
          meal_name: "Fish/Mozzarella Sticks with Chips and Broccoli",
          quick_meal_name: null,
          meal_image_url: null,
          time: null,
          member_ids: ["u1", "u2", "u3"],
          cook_member_id: null,
          makes_leftovers: false,
          is_favourite: false,
        },
      ],
    });

    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      member(),
      member({ user_id: "u2", display_name: "Alex" }),
      member({ user_id: "u3", display_name: "Sam" }),
    ]);
    render(<MealPlansPage />);
    const card = await screen.findByRole("button", {
      name: /fish\/mozzarella sticks with chips and broccoli/i,
    });
    const body = card.querySelector(".mealplan-slot-body");
    const title = card.querySelector(".mealplan-entry-title");
    expect(body).toHaveClass("text-shrinkable");
    expect(title).toHaveClass("text-wrap-anywhere");
    expect(title).toHaveTextContent("Fish/Mozzarella Sticks with Chips and Broccoli");
    expect(card.querySelector(".avatar")).toBeInTheDocument();
    expect(card.querySelector(".avatar-stack")).toBeInTheDocument();
    expect(card.querySelector(".mealplan-slot-actions")).toBeInTheDocument();
    expect(card.querySelector(".mealplan-slot-actions .mealplan-slot-chevron")).toBeInTheDocument();
    // jsdom does not perform layout; CSS min-width/flex sizing is verified by
    // the rendered hierarchy here and by the simulator retest.
  });

  it("shows a populated meal's real participants with a family icon and an overflow '+N' indicator, never hard-coded avatars", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
      date: "2026-08-29",
      entries: [
        {
          id: "entry-pizza",
          date: "2026-08-29",
          meal_slot: "dinner",
          meal_name: "Pizza Friday",
          quick_meal_name: null,
          meal_image_url: null,
          time: null,
          member_ids: ["u1", "u2", "u3", "u4"],
          cook_member_id: null,
          makes_leftovers: false,
          is_favourite: false,
        },
      ],
    });
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      member(),
      member({ user_id: "u2", display_name: "Alex" }),
      member({ user_id: "u3", display_name: "Sam" }),
      member({ user_id: "u4", display_name: "Robin" }),
    ]);

    render(<MealPlansPage />);
    const card = await screen.findByRole("button", { name: /pizza friday/i });

    // "Everyone" comes from real member/entry data (memberNamesFor), not a
    // hard-coded mockup label — every member here is assigned.
    expect(within(card).getByText("Everyone")).toBeInTheDocument();
    const stack = card.querySelector(".avatar-stack");
    expect(stack).toBeInTheDocument();
    expect(within(stack as HTMLElement).getByText("M")).toBeInTheDocument(); // Megan's initial fallback
    expect(within(stack as HTMLElement).getByText("+1")).toBeInTheDocument();
  });
});

describe("Meal Plans — Add meal sheet", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
  });

  async function openBreakfastAddSheet() {
    render(<MealPlansPage />);
    const user = userEvent.setup();
    await screen.findByRole("tab", { name: "Plan" });
    const breakfastSection = screen
      .getByText("Breakfast")
      .closest(".mealplan-slot-card");
    if (!breakfastSection) throw new Error("Breakfast section not found");
    await user.click(
      within(breakfastSection as HTMLElement).getByRole("button", {
        name: /add/i,
      }),
    );
    return user;
  }

  it("shows the slot-appropriate placeholder and keeps Date in its own field", async () => {
    await openBreakfastAddSheet();

    expect(
      await screen.findByPlaceholderText(/overnight oats/i),
    ).toBeInTheDocument();

    // Date is its own label/input pair, distinct from the Meal-slot and Time
    // controls — never a shared three-column row.
    const dateLabel = screen.getByText("Date").closest("label");
    expect(dateLabel?.querySelector('input[type="date"]')).toBeTruthy();
    expect(dateLabel?.querySelector("select")).toBeNull();

    expect(screen.getByLabelText(/time \(optional\)/i)).toHaveAttribute(
      "type",
      "time",
    );
  });

  it("submits a quick meal for the selected slot", async () => {
    const user = await openBreakfastAddSheet();
    const nameInput = await screen.findByPlaceholderText(/overnight oats/i);
    await user.type(nameInput, "Porridge");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createMealPlanEntry).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({
        quick_meal_name: "Porridge",
        meal_slot: "breakfast",
      }),
    );
  });
});

describe("Meal Plans — feature-gate consistency", () => {
  it("shows a calm message instead of the interactive planner when the module isn't released", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [{ feature: "meals", enabled: false }],
    });

    render(<MealPlansPage />);

    expect(
      await screen.findByText(/isn't available for this home yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Plan" })).not.toBeInTheDocument();
    // Never the raw backend "Not found" string this was built to replace.
    expect(screen.queryByText(/^not found$/i)).not.toBeInTheDocument();
  });
});

describe("Meal Plans — Meals library", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
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
    expect(
      screen.getByRole("button", { name: /add your first meal/i }),
    ).toBeInTheDocument();
  });

  it("adds a meal's ingredients to a chosen list, handling the confirm-duplicates step", async () => {
    (api.meals as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [meal()],
    });
    (api.meal as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...meal(),
      instructions: null,
      source_url: null,
      created_by: "u1",
      ingredients: [
        {
          id: "ing-1",
          position: 0,
          text: "beef mince",
          quantity: "500",
          unit: "g",
        },
        { id: "ing-2", position: 1, text: "onion", quantity: "1", unit: null },
      ],
    });
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "list-1",
          name: "Groceries",
          item_count: 1,
          created_by: "u1",
          created_at: "",
          updated_at: "",
        },
      ],
    });
    (
      api.addIngredientsToList as ReturnType<typeof vi.fn>
    ).mockResolvedValueOnce({
      requires_confirmation: true,
      added_count: 0,
      duplicate_count: 1,
      duplicate_texts: ["500 g beef mince"],
      list_id: "list-1",
    });
    (
      api.addIngredientsToList as ReturnType<typeof vi.fn>
    ).mockResolvedValueOnce({
      requires_confirmation: false,
      added_count: 1,
      duplicate_count: 1,
      duplicate_texts: ["500 g beef mince"],
      list_id: "list-1",
    });

    render(<MealPlansPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Meals" }));
    await user.click(
      await screen.findByRole("button", { name: /more actions for lasagne/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: /add ingredients to list/i }),
    );

    await screen.findByText("beef mince", { exact: false });
    await user.click(screen.getByRole("button", { name: /add 2 items/i }));

    expect(
      await screen.findByText(/already on groceries/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /add remaining/i }));

    expect(
      await screen.findByText(/added 1 item to groceries/i),
    ).toBeInTheDocument();
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
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      meals_enabled: true,
    });
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
    await user.click(
      await screen.findByRole("button", { name: /copy previous week/i }),
    );

    expect(
      await screen.findByText(/this will copy 3 planned meals/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^copy week$/i }));

    expect(await screen.findByText(/3 meals copied/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1 existing meal left unchanged/i),
    ).toBeInTheDocument();
    expect(api.copyMealPlanWeek).toHaveBeenCalledTimes(2);
  });
});
