import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BudgetEntrySheet } from "./budget-entry-sheet";

const apiMock = vi.hoisted(() => ({
  budgetCategories: vi.fn(),
  createBudgetEntry: vi.fn(),
}));

vi.mock("@mykhaya/api-client", () => ({ api: apiMock }));
vi.mock("@/components/bottom-sheet", () => ({
  BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div role="dialog" aria-label={title}>{children}</div>
  ),
}));

describe("Budget add spending entry sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Groceries" }]);
    apiMock.createBudgetEntry.mockResolvedValue({ id: "entry-1" });
  });

  it("creates an entry for the originating month and refreshes before closing", async () => {
    const onClose = vi.fn();
    const onSaved = vi.fn().mockResolvedValue(undefined);
    render(<BudgetEntrySheet homeId="home-1" initialCategoryId="cat-1" initialSpentOn="2026-09-01" onClose={onClose} onSaved={onSaved} />);

    fireEvent.change(await screen.findByLabelText("Description"), { target: { value: "Tesco" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "74.22" } });
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));

    await waitFor(() => expect(apiMock.createBudgetEntry).toHaveBeenCalledWith("home-1", {
      category_id: "cat-1",
      description: "Tesco",
      amount: 74.22,
      spent_on: "2026-09-01",
    }));
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the sheet and entered values after a failed create", async () => {
    apiMock.createBudgetEntry.mockRejectedValueOnce(new Error("request failed"));
    render(<BudgetEntrySheet homeId="home-1" initialCategoryId="cat-1" initialSpentOn="2026-09-01" onClose={vi.fn()} onSaved={vi.fn()} />);

    const description = await screen.findByLabelText("Description");
    fireEvent.change(description, { target: { value: "Tesco" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "74.22" } });
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t save spending entry. Please try again.");
    expect(screen.getByRole("dialog", { name: "Add spending entry" })).toBeInTheDocument();
    expect(description).toHaveValue("Tesco");
    expect(screen.getByRole("button", { name: "Add entry" })).not.toBeDisabled();
  });
});
