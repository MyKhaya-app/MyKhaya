import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BudgetItemList } from "./budget-item-list";

const apiMock = vi.hoisted(() => ({
  budgetMonth: vi.fn(),
  budgetItems: vi.fn(),
  updateBudgetItem: vi.fn(),
  deleteBudgetItem: vi.fn(),
}));

vi.mock("@mykhaya/api-client", () => ({ api: apiMock }));
vi.mock("@/components/bottom-sheet", () => ({
  BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div role="dialog" aria-label={title}>{children}</div>
  ),
}));
vi.mock("./budget-entry-sheet", () => ({
  BudgetEntrySheet: ({ initialFixedItem }: { initialFixedItem?: { description: string } }) => (
    <div data-testid="pay-sheet">{initialFixedItem?.description}</div>
  ),
}));

const monthWithItems = (items: unknown[]) => ({
  categories: [{ category_id: "cat-1", items }],
});

describe("Budget planned item list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a NOT PAID / PAID pill for fixed items only, without adding a wrapping element around the row", async () => {
    apiMock.budgetMonth.mockResolvedValue(
      monthWithItems([
        { id: "item-fixed", budget_item_id: "b-1", category_id: "cat-1", name: "Vehicle Loan", item_type: "fixed", planned_amount: 435, payment_status: "not_paid" },
        { id: "item-variable", budget_item_id: "b-2", category_id: "cat-1", name: "Groceries", item_type: "variable", planned_amount: 300 },
      ]),
    );
    render(<BudgetItemList homeId="home-1" categoryId="cat-1" year={2026} month={9} onRefresh={vi.fn()} />);

    const fixedRow = (await screen.findByText("Vehicle Loan")).closest("button");
    expect(fixedRow).not.toBeNull();
    expect(fixedRow).toHaveTextContent("NOT PAID");
    expect(fixedRow?.tagName).toBe("BUTTON");

    const variableRow = screen.getByText("Groceries").closest("button");
    expect(variableRow).not.toHaveTextContent("PAID");
  });

  it("shows Mark as paid for an unpaid fixed item and opens the pre-filled entry sheet", async () => {
    apiMock.budgetMonth.mockResolvedValue(
      monthWithItems([
        { id: "item-fixed", budget_item_id: "b-1", category_id: "cat-1", name: "Vehicle Loan", item_type: "fixed", planned_amount: 435, payment_status: "not_paid", starts_on: "2026-09-01", ends_on: null },
      ]),
    );
    render(<BudgetItemList homeId="home-1" categoryId="cat-1" year={2026} month={9} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByText("Vehicle Loan"));
    fireEvent.click(await screen.findByRole("button", { name: "Mark as paid" }));

    expect(await screen.findByTestId("pay-sheet")).toHaveTextContent("Vehicle Loan");
  });

  it("shows View transaction instead of Mark as paid once an item is paid", async () => {
    apiMock.budgetMonth.mockResolvedValue(
      monthWithItems([
        {
          id: "item-fixed", budget_item_id: "b-1", category_id: "cat-1", name: "Vehicle Loan", item_type: "fixed",
          planned_amount: 435, payment_status: "paid", paid_entry: { id: "entry-1", amount: 435, spent_on: "2026-09-01" },
          starts_on: "2026-09-01", ends_on: null,
        },
      ]),
    );
    const onViewTransaction = vi.fn();
    render(<BudgetItemList homeId="home-1" categoryId="cat-1" year={2026} month={9} onRefresh={vi.fn()} onViewTransaction={onViewTransaction} />);

    fireEvent.click(await screen.findByText("Vehicle Loan"));
    expect(screen.queryByRole("button", { name: "Mark as paid" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "View transaction" }));
    expect(onViewTransaction).toHaveBeenCalledWith("entry-1");
  });
});
