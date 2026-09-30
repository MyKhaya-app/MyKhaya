import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BudgetCategoryDetail } from "./budget-category-detail";

const apiMock = vi.hoisted(() => ({
  budgetCategories: vi.fn(),
  budgetMonth: vi.fn(),
  budgetEntries: vi.fn(),
  createBudgetMonth: vi.fn(),
  updateBudgetPlan: vi.fn(),
  updateBudgetActual: vi.fn(),
  updateBudgetCategoryNote: vi.fn(),
}));
const routerMock = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/budget/categories/cat-1",
  useSearchParams: () => new URLSearchParams("year=2026&month=10"),
  useRouter: () => routerMock,
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@mykhaya/api-client")>()), api: apiMock }));
vi.mock("@/components/bottom-sheet", () => ({ BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => <div role="dialog" aria-label={title}>{children}</div> }));
vi.mock("./budget-add-action", () => ({ BudgetAddAction: () => null }));
vi.mock("./budget-entry-sheet", () => ({ BudgetEntrySheet: () => null, periodDate: () => "2026-09-01" }));
vi.mock("./budget-item-list", () => ({ BudgetItemList: () => null }));

const month = { id: "month-1", year: 2026, month: 10, categories: [{ id: "month-cat-1", category_id: "cat-1", category_name: "Housing", planned_amount: 350, actual_source: "manual", manual_actual: null, fixed_actual: 0, entries_actual: 50, actual_amount: 50 }], income: [] };

describe("Budget category detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Housing", sort_order: 0, archived: false }]);
    apiMock.budgetMonth.mockResolvedValue(month);
    apiMock.budgetEntries.mockResolvedValue([{ id: "entry-1", category_id: "cat-1", description: "Primark", amount: 50, spent_on: "2026-10-01" }]);
  });

  it("shows persisted category transactions and entry-based totals", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByText("Primark")).toBeInTheDocument();
    expect(screen.getAllByText("£50.00").length).toBeGreaterThan(0);
    expect(screen.queryByText("No spending yet")).not.toBeInTheDocument();
    expect(apiMock.budgetMonth).toHaveBeenCalledWith("home-1", 2026, 10);
    expect(apiMock.budgetEntries).toHaveBeenCalledWith("home-1", { year: 2026, month: 10 });
  });

  it("keeps quick actions collapsed until opened", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    const toggle = await screen.findByRole("button", { name: "Quick actions" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Add spending entry" })).toBeInTheDocument();
  });

  it("moves the selected period with the category detail", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    await screen.findByText("October 2026");
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(routerMock.replace).toHaveBeenCalledWith("/budget/categories/cat-1?year=2026&month=9");
  });

  it("opens an existing transaction in the edit sheet", async () => {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByRole("button", { name: "Edit transaction Primark" })).toBeInTheDocument();
  });

  it("shows an unconfigured state when the selected future period is missing", async () => {
    apiMock.budgetMonth.mockResolvedValueOnce({ configured: false, id: null, year: 2026, month: 10, categories: [], income: [] });
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByText("This Budget period has not been set up yet.")).toBeInTheDocument();
    expect(screen.queryByText("Loading category details…")).not.toBeInTheDocument();
    expect(apiMock.budgetMonth).toHaveBeenCalledTimes(1);
    expect(apiMock.budgetEntries).not.toHaveBeenCalled();
  });

  it("does not stay loading when the period exists without the category", async () => {
    apiMock.budgetMonth.mockResolvedValueOnce({ ...month, categories: [] });
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    expect(await screen.findByText("This category is not included in the selected Budget period.")).toBeInTheDocument();
    expect(screen.queryByText("Loading category details…")).not.toBeInTheDocument();
  });

  it("loads the same period after setting it up without a refresh loop", async () => {
    apiMock.budgetMonth
      .mockResolvedValueOnce({ configured: false, id: null, year: 2026, month: 10, categories: [], income: [] })
      .mockResolvedValueOnce(month);
    apiMock.createBudgetMonth.mockResolvedValueOnce(month);
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up this period" }));
    expect(await screen.findByText("Primark")).toBeInTheDocument();
    expect(apiMock.createBudgetMonth).toHaveBeenCalledWith("home-1", 2026, 10);
    await waitFor(() => expect(apiMock.budgetMonth).toHaveBeenCalledTimes(2));
  });
});
