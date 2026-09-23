import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BudgetCategoryDetail } from "./budget-category-detail";

const apiMock = vi.hoisted(() => ({
  budgetCategories: vi.fn(),
  budgetMonth: vi.fn(),
  budgetEntries: vi.fn(),
  updateBudgetPlan: vi.fn(),
  updateBudgetActual: vi.fn(),
  updateBudgetCategoryNote: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/budget/categories/cat-1" }));
vi.mock("@mykhaya/api-client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@mykhaya/api-client")>()), api: apiMock }));
vi.mock("@/components/bottom-sheet", () => ({ BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => <div role="dialog" aria-label={title}>{children}</div> }));
vi.mock("./budget-add-action", () => ({ BudgetAddAction: () => null }));
vi.mock("./budget-entry-sheet", () => ({ BudgetEntrySheet: () => null, periodDate: () => "2026-09-01" }));
vi.mock("./budget-item-list", () => ({ BudgetItemList: () => null }));

const month = { id: "month-1", year: 2026, month: 9, categories: [{ id: "month-cat-1", category_id: "cat-1", category_name: "Housing", planned_amount: 350, actual_source: "manual", manual_actual: null, fixed_actual: 0, entries_actual: 50, actual_amount: 50 }], income: [] };

describe("Budget category detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Housing", sort_order: 0, archived: false }]);
    apiMock.budgetMonth.mockResolvedValue(month);
    apiMock.budgetEntries.mockResolvedValue([{ id: "entry-1", category_id: "cat-1", description: "Primark", amount: 50, spent_on: "2026-09-01" }]);
  });

  it("shows persisted category transactions and entry-based totals", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByText("Primark")).toBeInTheDocument();
    expect(screen.getByText("£50.00")).toBeInTheDocument();
    expect(screen.getByText("No spending yet")).not.toBeInTheDocument();
  });

  it("keeps quick actions collapsed until opened", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    const toggle = await screen.findByRole("button", { name: "Quick actions" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Add spending entry" })).toBeInTheDocument();
  });

  it("opens an existing transaction in the edit sheet", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByRole("button", { name: "Edit transaction Primark" })).toBeInTheDocument();
  });
});
