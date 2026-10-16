import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@mykhaya/api-client";
import { BudgetModule, BudgetOverviewWithAdd } from "./budget-module-wired";
import { BudgetModuleSheets } from "./budget-module-sheets";

const push = vi.fn();
const pathname = vi.hoisted(() => ({ value: "/budget" }));
const apiMock = vi.hoisted(() => ({
  budgetProfile: vi.fn(),
  budgetCategories: vi.fn(),
  budgetMonth: vi.fn(),
  createBudgetMonth: vi.fn(),
  createBudgetCategory: vi.fn(),
  createBudgetIncomeSource: vi.fn(),
  budgetIncomeSources: vi.fn(),
  updateBudgetMonthIncome: vi.fn(),
  updateBudgetIncomeSource: vi.fn(),
  deleteBudgetIncomeSource: vi.fn(),
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
  usePathname: () => pathname.value,
}));
type Access = { billing: { budget_enabled: boolean }; features: { features: { feature: string; enabled: boolean }[] } };
const homeAccess = vi.hoisted(() => ({ value: null as null | { state: "ready"; value: Access } | { state: "loading" } }));
function planAccess(budgetEnabled: boolean, released = true) {
  homeAccess.value = { state: "ready", value: { billing: { budget_enabled: budgetEnabled }, features: { features: [{ feature: "budget", enabled: released }] } } };
}
vi.mock("@/components/home-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/home-access")>()),
  useHomeAccess: () => ({ access: homeAccess.value, refresh: vi.fn() }),
}));
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({ activeHomeId: "home-1" }),
}));
vi.mock("@/components/app-shell", () => ({ AppShellContent: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/bottom-sheet", () => ({ BottomSheet: ({ title, children }: { title: string; children: React.ReactNode }) => <div role="dialog" aria-label={title}>{children}</div> }));
vi.mock("@mykhaya/api-client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@mykhaya/api-client")>()), api: apiMock }));

const month = { id: "month-1", year: 2026, month: 9, categories: [{ id: "month-cat-1", category_id: "cat-1", category_name: "Groceries", planned_amount: 600, actual_source: "entries", manual_actual: null, entries_actual: 74.22, actual_amount: 74.22 }], income: [{ id: "income-1", source_id: "source-1", source_name: "Salary", expected_amount: 4850, received_amount: 4200, usual_payday_day: 25, recurring: true, expected_date: "2026-09-25", received_date: null, budget_year: 2026, budget_month: 9 }] };

beforeEach(() => {
  vi.clearAllMocks();
  planAccess(true);
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
    fireEvent.click(await screen.findByRole("button", { name: /Salary/ }));
    fireEvent.change(screen.getByLabelText("Expected amount (per month)"), { target: { value: "4900" } });
    fireEvent.change(screen.getByLabelText("Received amount (per month)"), { target: { value: "4300" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(apiMock.updateBudgetMonthIncome).toHaveBeenCalledWith("home-1", 2026, 9, "source-1", { expected_amount: 4900, received_amount: 4300, received_date: null, budget_year: 2026, budget_month: 9 }));
  });

  it("opens the add-income BottomSheet and closes after saving", async () => {
    apiMock.createBudgetIncomeSource.mockResolvedValue({ id: "source-2", name: "NNUH", sort_order: 0, archived: false });
    apiMock.budgetMonth
      .mockResolvedValueOnce(month)
      .mockResolvedValueOnce({ ...month, income: [...month.income, { id: "income-2", source_id: "source-2", source_name: "NNUH", expected_amount: 0, received_amount: 0 }] });
    render(<BudgetModule screen="income" />);
    fireEvent.click(await screen.findByRole("button", { name: /Add income source/ }));
    expect(screen.getByRole("dialog", { name: "Add income source" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "NNUH" } });
    fireEvent.click(screen.getByRole("button", { name: "Create income source" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add income source" })).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: /NNUH/ })).toBeInTheDocument();
  });

  it("opens edit and then the destructive income-source confirmation", async () => {
    render(<BudgetModule screen="income" />);
    fireEvent.click(await screen.findByRole("button", { name: /Salary/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delete income source" }));
    expect(screen.getByRole("dialog", { name: "Delete income source?" })).toBeInTheDocument();
    expect(screen.getByText(/Historical data will be kept/)).toBeInTheDocument();
  });

  it("shows a friendly duplicate income-source error and keeps the entered name", async () => {
    apiMock.createBudgetIncomeSource.mockRejectedValueOnce(
      new ApiError(409, "Income source already exists"),
    );
    render(<BudgetModule screen="income" />);
    fireEvent.click(await screen.findByRole("button", { name: /Add income source/ }));
    const input = await screen.findByLabelText("Source name");
    fireEvent.change(input, { target: { value: "NNUH" } });
    fireEvent.click(screen.getByRole("button", { name: "Create income source" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Income source already exists",
    );
    expect(input).toHaveValue("NNUH");
    expect(screen.getByRole("button", { name: "Create income source" })).not.toBeDisabled();
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
    await waitFor(() => {
      expect(apiMock.sharedBudgetMonth).toHaveBeenCalledWith(
        "home-1",
        "owner-1",
        expect.any(Number),
        expect.any(Number),
      );
    });
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

  it("offers the Ultimate upgrade, like Driveway, when the plan does not include Budget", async () => {
    planAccess(false);
    apiMock.budgetProfile.mockRejectedValue(new ApiError(403, "Budget is included with Ultimate.", "plan_feature_unavailable"));
    render(<BudgetModule screen="overview" />);
    expect(await screen.findByText("Included with MyKhaya Ultimate.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View plans" })).toHaveAttribute("href", "/settings/billing");
    expect(screen.queryByText(/has not enabled Budget/)).not.toBeInTheDocument();
    expect(apiMock.budgetCategories).not.toHaveBeenCalled();
  });

  it("says Budget is not available yet when the module is not released", async () => {
    planAccess(true, false);
    apiMock.budgetProfile.mockRejectedValue(new Error("not released"));
    render(<BudgetModule screen="overview" />);
    expect(await screen.findByText(/isn't available for this Home yet/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View plans" })).not.toBeInTheDocument();
  });

  it("never reveals Budget content from plan state alone: the API stays the gate", async () => {
    planAccess(true);
    apiMock.budgetProfile.mockRejectedValue(new ApiError(403, "Budget is included with Ultimate.", "plan_feature_unavailable"));
    render(<BudgetModule screen="overview" />);
    expect(await screen.findByText("Budget isn’t available here")).toBeInTheDocument();
    expect(apiMock.budgetMonth).not.toHaveBeenCalled();
  });

  it("does not offer the Add action on the upgrade screen, like Driveway", async () => {
    planAccess(false);
    apiMock.budgetProfile.mockRejectedValue(new ApiError(403, "Budget is included with Ultimate.", "plan_feature_unavailable"));
    render(<BudgetOverviewWithAdd />);
    expect(await screen.findByText("Included with MyKhaya Ultimate.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Budget item" })).not.toBeInTheDocument();
  });

  it("keeps the Add action once Budget is available", async () => {
    render(<BudgetOverviewWithAdd />);
    expect(await screen.findByRole("button", { name: "Add Budget item" })).toBeInTheDocument();
  });

  it("uses the same upgrade message on the sheet-based Budget screens", async () => {
    planAccess(false);
    apiMock.budgetProfile.mockRejectedValue(new ApiError(403, "Budget is included with Ultimate.", "plan_feature_unavailable"));
    render(<BudgetModuleSheets screen="spending" />);
    expect(await screen.findByText("Included with MyKhaya Ultimate.")).toBeInTheDocument();
    expect(apiMock.budgetEntries).not.toHaveBeenCalled();
  });
});
