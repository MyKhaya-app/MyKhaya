import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BudgetTabs } from "./budget-tabs";

const pathname = vi.hoisted(() => ({ value: "/budget" }));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

describe("BudgetTabs", () => {
  it.each([
    ["/budget", "Overview"],
    ["/budget/categories", "Categories"],
    ["/budget/income", "Income"],
    ["/budget/settings", "Settings"],
  ])("marks %s as active", (route, activeLabel) => {
    pathname.value = route;
    render(<BudgetTabs />);

    expect(screen.getByRole("navigation", { name: "Budget sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Overview",
      "Categories",
      "Income",
      "Settings",
    ]);
    expect(screen.getByRole("link", { name: activeLabel })).toHaveClass("active");
  });
});
