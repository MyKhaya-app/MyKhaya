import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BudgetModule } from "./budget-module-wired";

const push = vi.fn();
const apiMock = vi.hoisted(() => ({
  budgetProfile: vi.fn(),
  budgetCategories: vi.fn(),
  budgetMonth: vi.fn(),
  createBudgetMonth: vi.fn(),
  createBudgetCategory: vi.fn(),
  createBudgetIncomeSource: vi.fn(),
  budgetIncomeSources: vi.fn(),
  updateBudgetMonthIncome: vi.fn(),
  budgetEntries: vi.fn(),
  budgetEntry: vi.fn(),
  sharedBudgetMonth: vi.fn(),
  createBudgetEntry: vi.fn(),
  updateBudgetEntry: vi.fn(),
  deleteBudgetEntry: vi.fn(),
  budgetSettings: vi.fn(),
  updateBudgetSettings: vi.fn(),
  incomingBudgetShares: vi.fn(),
  budgetShares: vi.fn(),
  members: vi.fn(),
  setBudgetShare: vi.fn(),
  revokeBudgetShare: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({ activeHomeId: "home-1" }),
}));
vi.mock("@/components/app-shell", () => ({ AppShellContent: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/bottom-sheet", () => ({ BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => <div role="dialog" aria-label={title}>{children}</div> }));
vi.mock("@mykhaya/api-client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@mykhaya/api-client")>()), api: apiMock }));

const month = { id: "month-1", year: 2026, month: 9, categories: [{ id: "month-cat-1", category_id: "cat-1", category_name: "Groceries", planned_amount: 600, actual_source: "entries", manual_actual: null, entries_actual: 74.22, actual_amount: 74.22 }], income: [{ id: "income-1", source_id: "source-1", source_name: "Salary", expected_amount: 4850, received_amount: 4200 }] };

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.budgetProfile.mockResolvedValue({ id: "profile-1", owner_user_id: "user-1", currency: "GBP", month_start_day: 1, archived: false });
  apiMock.incomingBudgetShares.mockResolvedValue([]);
  apiMock.budgetShares.mockResolvedValue([]);
  apiMock.budgetMonth.mockResolvedValue(month);
  apiMock.budgetCategories.mockResolvedValue([{ id: "cat-1", name: "Groceries", sort_order: 0, archived: false }]);
  apiMock.budgetEntries.mockResolvedValue([{ id: "entry-1", category_id: "cat-1", description: "Tesco", amount: 74.22, spent_on: "2026-09-20" }]);
  apiMock.budgetEntry.mockResolvedValue({ id: "entry-1", category_id: "cat-1", description: "Tesco", amount: 74.22, spent_on: "2026-09-20" });
  apiMock.budgetSettings.mockResolvedValue({ id: "profile-1", owner_user_id: "user-1", currency: "GBP", month_start_day: 1, archived: false });
  apiMock.sharedBudgetMonth.mockResolvedValue(month);
});

describe("Budget consumer API wiring", () => {
  it("renders the spending-entry list from the selected month", async () => {
    render(<BudgetModule screen="spending" />);
    expect(await screen.findByText("Tesco")).toBeInTheDocument();
    expect(apiMock.budgetEntries).toHaveBeenCalled();
  });

  it("loads, edits and deletes spending entries", async () => {
    render(<BudgetModule screen="entry-edit" entryId="entry-1" />);
    expect(await screen.findByDisplayValue("Tesco")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Updated Tesco" } });
    fireEvent.click(screen.getByRole("button", { name: "Save entry" }));
    await waitFor(() => expect(apiMock.updateBudgetEntry).toHaveBeenCalledWith("home-1", "entry-1", expect.objectContaining({ description: "Updated Tesco" })));

    render(<BudgetModule screen="spending" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Tesco" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete entry" }));
    await waitFor(() => expect(apiMock.deleteBudgetEntry).toHaveBeenCalledWith("home-1", "entry-1"));
  });

  it("saves monthly expected and received income", async () => {
    render(<BudgetModule screen="income" />);
    fireEvent.change(await screen.findByLabelText("Expected"), { target: { value: "4900" } });
    fireEvent.change(screen.getByLabelText("Received"), { target: { value: "4300" } });
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    await waitFor(() => expect(apiMock.updateBudgetMonthIncome).toHaveBeenCalledWith("home-1", 2026, 9, "source-1", { expected_amount: 4900, received_amount: 4300 }));
  });

  it("loads and saves user-owned Budget settings", async () => {
    apiMock.updateBudgetSettings.mockResolvedValue({ id: "profile-1", owner_user_id: "user-1", currency: "EUR", month_start_day: 15, archived: false });
    render(<BudgetModule screen="settings" />);
    const input = await screen.findByLabelText("Currency");
    expect(input).toHaveValue("GBP");
    fireEvent.change(input, { target: { value: "EUR" } });
    fireEvent.change(await screen.findByLabelText("Month starts on"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(apiMock.updateBudgetSettings).toHaveBeenCalledWith("home-1", { currency: "EUR", month_start_day: 15 }));
  });

  it("shows Personal/Together only for an active relationship and uses shared discovery", async () => {
    apiMock.incomingBudgetShares.mockResolvedValue([{ home_id: "home-1", owner_user_id: "owner-1", owner_display_name: "Partner", level: "summary" }]);
    render(<BudgetModule screen="together" />);
    expect(await screen.findByRole("link", { name: "Partner" })).toBeInTheDocument();
    expect(apiMock.sharedBudgetMonth).toHaveBeenCalledWith("home-1", "owner-1", expect.any(Number), expect.any(Number));
  });

  it("does not show Together after a share is revoked", async () => {
    apiMock.budgetShares.mockResolvedValue([{ id: "share-1", partner_user_id: "partner-1", level: "summary", active: false }]);
    render(<BudgetModule screen="overview" />);
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Budget view" })).not.toBeInTheDocument());
  });

  it("fails closed when Budget is disabled", async () => {
    apiMock.budgetProfile.mockRejectedValue(new Error("disabled"));
    render(<BudgetModule screen="overview" />);
    expect(await screen.findByText("Budget isn’t available here")).toBeInTheDocument();
    expect(apiMock.budgetCategories).not.toHaveBeenCalled();
  });
});
