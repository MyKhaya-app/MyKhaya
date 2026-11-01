import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BudgetEditEntrySheet } from "./budget-edit-entry-sheet";
import { BudgetAddAction } from "./budget-add-action";
import { BudgetItemList } from "./budget-item-list";
import { BudgetMonthCopy } from "./budget-month-copy";
import { budgetFieldErrors } from "./budget-form-fields";
import { BudgetModuleSheets } from "./budget-module-sheets";

// Budget's forms on the shared form primitives (docs/design/forms.md):
// errors come from each control's own constraints, a blank amount is never
// sent as 0, an edit sends back every value it did not change, and a failed
// save keeps the draft.

const apiMock = vi.hoisted(() => ({
  budgetCategories: vi.fn(),
  budgetMonth: vi.fn(),
  budgetItems: vi.fn(),
  updateBudgetEntry: vi.fn(),
  deleteBudgetEntry: vi.fn(),
  createBudgetItem: vi.fn(),
  updateBudgetItem: vi.fn(),
  deleteBudgetItem: vi.fn(),
  copyBudgetMonth: vi.fn(),
  budgetProfile: vi.fn(),
  createBudgetCategory: vi.fn(),
  updateBudgetPlan: vi.fn(),
}));
const push = vi.fn();

vi.mock("@mykhaya/api-client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@mykhaya/api-client")>()), api: apiMock }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("year=2026&month=12"),
  usePathname: () => "/budget/categories",
}));
vi.mock("@/components/use-active-home", () => ({ useActiveHome: () => ({ activeHomeId: "home-1" }) }));
vi.mock("@/components/app-shell", () => ({ AppShellContent: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
// Renders the footer too: FormSheet puts Save and Cancel there.
vi.mock("@/components/bottom-sheet", () => ({
  BottomSheet: ({ title, children, footer }: { title: string; children: React.ReactNode; footer?: React.ReactNode }) => (
    <div role="dialog" aria-label={title}>{children}{footer}</div>
  ),
}));

const entry = {
  id: "entry-1",
  category_id: "cat-1",
  description: "Car insurance",
  amount: 412.37,
  spent_on: "2024-02-29",
  note: "Annual",
  budget_month_item_id: "month-item-1",
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Transport", sort_order: 0, archived: false }]);
  apiMock.budgetProfile.mockResolvedValue({ id: "profile-1", owner_user_id: "user-1", currency: "GBP", month_start_day: 1, default_view: "personal", archived: false });
});

describe("budgetFieldErrors", () => {
  function form(html: string) {
    const element = document.createElement("form");
    element.noValidate = true;
    element.innerHTML = html;
    return element;
  }

  it("reads each named control's own constraints", () => {
    const errors = budgetFieldErrors(form(`
      <input name="blank" type="number" min="0" step="0.01" required value="">
      <input name="negative" type="number" min="0" step="0.01" value="-1">
      <input name="zero" type="number" min="0.01" step="0.01" value="0">
      <input name="pence" type="number" min="0" step="0.01" value="12.345">
      <input name="payday" type="number" min="1" max="31" value="32">
      <input name="fine" type="number" min="0" step="0.01" value="12.50">
      <input value="" required>
    `), { blank: { missing: "Enter an amount." } });
    expect(errors).toEqual({
      blank: "Enter an amount.",
      negative: "Enter 0 or more.",
      zero: "Enter an amount greater than 0.",
      pence: "Use no more than 2 decimal places.",
      payday: "Enter a number from 1 to 31.",
    });
  });

  it("names a whole-number step and an unreadable entry", () => {
    // jsdom computes neither a number input's default step mismatch nor
    // badInput, so the browser's verdict is supplied here.
    const verdict = (input: HTMLInputElement, flags: Partial<ValidityState>) => {
      Object.defineProperty(input, "validity", { value: { valid: false, badInput: false, valueMissing: false, rangeUnderflow: false, rangeOverflow: false, stepMismatch: false, ...flags } });
      return input;
    };
    const element = form(`<input name="whole" type="number"><input name="amount" type="number" step="0.01"><input name="date" type="date"><input name="due" type="date" required>`);
    const [whole, amount, date, due] = Array.from(element.querySelectorAll("input"));
    verdict(whole!, { stepMismatch: true });
    verdict(amount!, { badInput: true });
    verdict(date!, { badInput: true });
    verdict(due!, { badInput: true });
    expect(budgetFieldErrors(element)).toEqual({
      whole: "Enter a whole number.",
      amount: "Enter an amount, like 12.50.",
      date: "Enter a full date, or clear it.",
      due: "Enter a full date.",
    });
  });

  it("rejects a spaces-only value only where the form trims it", () => {
    const element = form(`<input name="name" value="   " required><input name="description" value="   " required>`);
    expect(budgetFieldErrors(element, { name: { blank: "Enter a name." } })).toEqual({ name: "Enter a name." });
  });
});

describe("Edit spending entry", () => {
  it("sends back every value it did not change, including the paid link and a leap day", async () => {
    apiMock.updateBudgetEntry.mockResolvedValue({});
    const onSaved = vi.fn();
    render(<BudgetEditEntrySheet homeId="home-1" entry={entry} onClose={vi.fn()} onSaved={onSaved} />);
    await screen.findByRole("option", { name: "Transport" });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Car insurance renewal" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(apiMock.updateBudgetEntry).toHaveBeenCalledWith("home-1", "entry-1", {
      category_id: "cat-1",
      description: "Car insurance renewal",
      amount: 412.37,
      spent_on: "2024-02-29",
      note: "Annual",
      budget_month_item_id: "month-item-1",
    }));
    expect(onSaved).toHaveBeenCalled();
  });

  it("shows a blank amount on the Amount field, focuses it and sends nothing", async () => {
    render(<BudgetEditEntrySheet homeId="home-1" entry={entry} onClose={vi.fn()} onSaved={vi.fn()} />);
    const amount = screen.getByLabelText("Amount");
    fireEvent.change(amount, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Enter an amount.")).toBeInTheDocument();
    expect(amount).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(amount).toHaveFocus());
    expect(apiMock.updateBudgetEntry).not.toHaveBeenCalled();
    fireEvent.change(amount, { target: { value: "0" } });
    expect(screen.queryByText("Enter an amount.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Enter an amount greater than 0.")).toBeInTheDocument();
    expect(apiMock.updateBudgetEntry).not.toHaveBeenCalled();
  });

  it("keeps the draft and restores Save and Cancel after a failed save", async () => {
    apiMock.updateBudgetEntry.mockRejectedValue(new Error("offline"));
    const onClose = vi.fn();
    render(<BudgetEditEntrySheet homeId="home-1" entry={entry} onClose={onClose} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "415.10" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t save spending entry");
    expect(screen.getByLabelText("Amount")).toHaveValue(415.1);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Cancel closes without saving", () => {
    const onClose = vi.fn();
    render(<BudgetEditEntrySheet homeId="home-1" entry={entry} onClose={onClose} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Changed" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(apiMock.updateBudgetEntry).not.toHaveBeenCalled();
  });
});

describe("Add fixed cost", () => {
  it("does not send a blank amount as 0, then saves the entered amount unrounded", async () => {
    apiMock.createBudgetItem.mockResolvedValue({});
    render(<BudgetAddAction homeId="home-1" onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Budget item" }));
    fireEvent.click(screen.getByRole("button", { name: /Fixed monthly cost/ }));
    await screen.findByRole("option", { name: "Transport" });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Car finance" } });
    fireEvent.click(screen.getByRole("button", { name: "Add fixed cost" }));
    expect(await screen.findByText("Enter an amount.")).toBeInTheDocument();
    expect(apiMock.createBudgetItem).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Name")).toHaveValue("Car finance");

    fireEvent.change(screen.getByLabelText("Monthly amount"), { target: { value: "199.99" } });
    fireEvent.click(screen.getByRole("button", { name: "Add fixed cost" }));
    const now = new Date();
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    await waitFor(() => expect(apiMock.createBudgetItem).toHaveBeenCalledWith("home-1", {
      category_id: "cat-1",
      name: "Car finance",
      item_type: "fixed",
      default_amount: 199.99,
      recurring: true,
      starts_on: `${month}-01`,
      ends_on: null,
      notes: null,
      year: now.getFullYear(),
      month: now.getMonth() + 1,
    }));
  });

  it("shows an end month before the start month on the End month field", async () => {
    render(<BudgetAddAction homeId="home-1" onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Budget item" }));
    fireEvent.click(screen.getByRole("button", { name: /Fixed monthly cost/ }));
    await screen.findByRole("option", { name: "Transport" });
    fireEvent.change(screen.getByLabelText("Monthly amount"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Start month"), { target: { value: "2026-11" } });
    fireEvent.change(screen.getByLabelText("End month"), { target: { value: "2026-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Add fixed cost" }));
    expect(await screen.findByText("Choose an end month on or after the start month.")).toBeInTheDocument();
    expect(screen.getByLabelText("End month")).toHaveAccessibleDescription(/Leave empty for no end date/);
    expect(apiMock.createBudgetItem).not.toHaveBeenCalled();
  });
});

describe("Edit planned item", () => {
  it("changes only the name and planned amount it shows, keeping the item's defaults", async () => {
    apiMock.budgetMonth.mockResolvedValue({ categories: [{ category_id: "cat-1", items: [
      { id: "mi-1", budget_item_id: "item-1", category_id: "cat-1", name: "Car finance", item_type: "fixed", planned_amount: 199.99, payment_status: "paid", starts_on: "2026-01-01", ends_on: "2027-12-01" },
    ] }] });
    apiMock.budgetItems.mockResolvedValue([{ id: "item-1", category_id: "cat-1", name: "Car finance", item_type: "fixed", default_amount: 205, recurring: true, starts_on: "2026-01-01", ends_on: "2027-12-01", notes: "PCP", archived: false }]);
    apiMock.updateBudgetItem.mockResolvedValue({});
    render(<BudgetItemList homeId="home-1" categoryId="cat-1" year={2026} month={12} onRefresh={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Car finance/ }));
    fireEvent.click(screen.getByRole("button", { name: "Edit item" }));
    const name = await screen.findByLabelText("Name");
    fireEvent.change(name, { target: { value: "Car finance (PCP)" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(apiMock.updateBudgetItem).toHaveBeenCalledWith("home-1", "item-1", {
      name: "Car finance (PCP)",
      default_amount: 205,
      recurring: true,
      starts_on: "2026-01-01",
      ends_on: "2027-12-01",
      notes: "PCP",
      year: 2026,
      month: 12,
      planned_amount: 199.99,
    }));
  });
});

describe("Add category", () => {
  it("asks only for what it saves: a name, created in the month in view", async () => {
    apiMock.budgetMonth.mockResolvedValue({ id: "m", year: 2026, month: 12, categories: [], income: [] });
    apiMock.createBudgetCategory.mockResolvedValue({ id: "cat-new", name: "Pets", sort_order: 0, archived: false });
    render(<BudgetModuleSheets screen="categories" />);
    fireEvent.click(await screen.findByRole("button", { name: /Add category/ }));
    const dialog = screen.getByRole("dialog", { name: "Add category" });
    expect(dialog.querySelectorAll("input, select, textarea")).toHaveLength(1);
    expect(screen.queryByLabelText(/Planned amount/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create category" }));
    expect(await screen.findByText("Enter a category name.")).toBeInTheDocument();
    expect(apiMock.createBudgetCategory).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Category name"), { target: { value: "Pets" } });
    fireEvent.click(screen.getByRole("button", { name: "Create category" }));
    await waitFor(() => expect(apiMock.createBudgetCategory).toHaveBeenCalledWith("home-1", { name: "Pets", year: 2026, month: 12 }));
    expect(apiMock.updateBudgetPlan).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add category" })).not.toBeInTheDocument());
  });
});

describe("Set up next month", () => {
  it("copies into January of the next year from December, with the existing defaults", async () => {
    apiMock.copyBudgetMonth.mockResolvedValue({});
    render(<BudgetMonthCopy homeId="home-1" year={2026} month={12} />);
    fireEvent.click(screen.getByRole("button", { name: /Set up January 2027/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create January 2027 plan" }));
    await waitFor(() => expect(apiMock.copyBudgetMonth).toHaveBeenCalledWith("home-1", 2027, 1, {
      copy_fixed_items: true,
      copy_variable_items: false,
      copy_income_sources: true,
    }));
    expect(push).toHaveBeenCalledWith("/budget/categories?year=2027&month=1");
  });

  it("keeps the sheet and its choices after a failed copy", async () => {
    apiMock.copyBudgetMonth.mockRejectedValue(new Error("offline"));
    render(<BudgetMonthCopy homeId="home-1" year={2026} month={10} />);
    fireEvent.click(screen.getByRole("button", { name: /Set up November 2026/ }));
    fireEvent.click(screen.getByLabelText("Copy variable budgets"));
    fireEvent.click(screen.getByRole("button", { name: "Create November 2026 plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t create the next month");
    expect(screen.getByLabelText("Copy variable budgets")).toBeChecked();
    expect(screen.getByRole("button", { name: "Create November 2026 plan" })).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });
});
