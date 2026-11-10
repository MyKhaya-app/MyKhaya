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
// Renders the footer too: FormSheet puts Save and Cancel there.
vi.mock("@/components/bottom-sheet", () => ({ BottomSheet: ({ title, children, footer }: { title: string; children: React.ReactNode; footer?: React.ReactNode }) => <div role="dialog" aria-label={title}>{children}{footer}</div> }));
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

describe("Update actual amount", () => {
  // fixed_actual is the category's own amount; the API adds entries to it.
  const additive = { ...month, categories: [{ ...month.categories[0]!, fixed_actual: 120.4, entries_actual: 50, actual_amount: 170.4 }] };
  const legacyEntries = { ...month, categories: [{ ...month.categories[0]!, actual_source: "entries", manual_actual: null, fixed_actual: null, entries_actual: 50, actual_amount: 50 }] };
  const legacyManual = { ...month, categories: [{ ...month.categories[0]!, actual_source: "manual", manual_actual: 80.25, fixed_actual: null, entries_actual: 50, actual_amount: 80.25 }] };

  async function openActual() {
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Quick actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Update actual amount" }));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Housing", sort_order: 0, archived: false }]);
    apiMock.budgetEntries.mockResolvedValue([]);
  });

  it("opens on the stored amount, follows typing, and saves exactly what is shown", async () => {
    apiMock.budgetMonth.mockResolvedValue(additive);
    apiMock.updateBudgetActual.mockResolvedValue({});
    await openActual();
    const input = screen.getByLabelText("Fixed monthly amount");
    expect(input).toHaveValue(120.4);
    fireEvent.change(input, { target: { value: "55" } });
    expect(input).toHaveValue(55);
    fireEvent.change(input, { target: { value: "55.07" } });
    expect(input).toHaveValue(55.07);
    fireEvent.click(screen.getByRole("button", { name: "Save fixed amount" }));
    await waitFor(() => expect(apiMock.updateBudgetActual).toHaveBeenCalledWith("home-1", 2026, 10, "cat-1", { source: "manual", manual_actual: 55.07 }));
    expect(apiMock.updateBudgetActual).toHaveBeenCalledTimes(1);
    expect(apiMock.updateBudgetPlan).not.toHaveBeenCalled();
  });

  it("keeps what was typed when the page re-renders behind the sheet", async () => {
    // The defect: the input was bound to a value recomputed from the month on
    // every render, so typing never showed and each render reset it.
    apiMock.budgetMonth.mockResolvedValue(additive);
    const view = render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Quick actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Update actual amount" }));
    fireEvent.change(screen.getByLabelText("Fixed monthly amount"), { target: { value: "61.5" } });
    view.rerender(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Quick actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Quick actions" }));
    expect(screen.getByLabelText("Fixed monthly amount")).toHaveValue(61.5);
  });

  it("never starts from the entries total, which saving would count twice", async () => {
    apiMock.budgetMonth.mockResolvedValue(legacyEntries);
    await openActual();
    expect(screen.getByLabelText("Actual amount")).toHaveValue(0);
  });

  it("starts a hand-entered legacy row from its own amount, so saving it unchanged sends the same value", async () => {
    apiMock.budgetMonth.mockResolvedValue(legacyManual);
    apiMock.updateBudgetActual.mockResolvedValue({});
    await openActual();
    expect(screen.getByLabelText("Actual amount")).toHaveValue(80.25);
    fireEvent.click(screen.getByRole("button", { name: "Save actual" }));
    await waitFor(() => expect(apiMock.updateBudgetActual).toHaveBeenCalledWith("home-1", 2026, 10, "cat-1", { source: "manual", manual_actual: 80.25 }));
  });

  it("Cancel saves nothing, and reopening shows the stored amount again", async () => {
    apiMock.budgetMonth.mockResolvedValue(additive);
    await openActual();
    fireEvent.change(screen.getByLabelText("Fixed monthly amount"), { target: { value: "999" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Fixed monthly amount")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Update actual amount" }));
    expect(screen.getByLabelText("Fixed monthly amount")).toHaveValue(120.4);
    expect(apiMock.updateBudgetActual).not.toHaveBeenCalled();
  });

  it("keeps the draft and restores Save and Cancel after a failed save", async () => {
    apiMock.budgetMonth.mockResolvedValue(additive);
    apiMock.updateBudgetActual.mockRejectedValue(new Error("offline"));
    await openActual();
    fireEvent.change(screen.getByLabelText("Fixed monthly amount"), { target: { value: "42.42" } });
    fireEvent.click(screen.getByRole("button", { name: "Save fixed amount" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t save the amount");
    expect(screen.getByLabelText("Fixed monthly amount")).toHaveValue(42.42);
    expect(screen.getByRole("button", { name: "Save fixed amount" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("rejects a blank, negative or over-precise amount on the field and sends nothing", async () => {
    apiMock.budgetMonth.mockResolvedValue(additive);
    await openActual();
    const input = screen.getByLabelText("Fixed monthly amount");
    for (const [value, message] of [["", "Enter an amount."], ["-1", "Enter 0 or more."], ["12.345", "Use no more than 2 decimal places."]] as const) {
      fireEvent.change(input, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "Save fixed amount" }));
      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(input).toHaveAttribute("aria-invalid", "true");
    }
    expect(apiMock.updateBudgetActual).not.toHaveBeenCalled();
  });
});

describe("Edit planned amount", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Housing", sort_order: 0, archived: false }]);
    apiMock.budgetMonth.mockResolvedValue(month);
    apiMock.budgetEntries.mockResolvedValue([]);
  });

  it("saves the planned amount for the month in view only, without touching the actual", async () => {
    apiMock.updateBudgetPlan.mockResolvedValue({});
    render(<BudgetCategoryDetail homeId="home-1" categoryId="cat-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Quick actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit planned amount" }));
    const input = screen.getByLabelText("Planned amount (per month)");
    expect(input).toHaveValue(350);
    fireEvent.change(input, { target: { value: "412.37" } });
    fireEvent.click(screen.getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(apiMock.updateBudgetPlan).toHaveBeenCalledWith("home-1", 2026, 10, "cat-1", 412.37));
    expect(apiMock.updateBudgetPlan).toHaveBeenCalledTimes(1);
    expect(apiMock.updateBudgetActual).not.toHaveBeenCalled();
  });
});
