"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/budget", label: "Overview" },
  { href: "/budget/categories", label: "Categories" },
  { href: "/budget/income", label: "Income" },
  { href: "/budget/settings", label: "Settings" },
] as const;

export function BudgetTabs() {
  const pathname = usePathname();
  const activeHref = pathname === "/budget"
    ? "/budget"
    : pathname.startsWith("/budget/categories") || pathname === "/budget/edit-plan" || pathname.startsWith("/budget/spending")
      ? "/budget/categories"
      : pathname.startsWith("/budget/income")
        ? "/budget/income"
        : pathname.startsWith("/budget/settings") || pathname.startsWith("/budget/sharing")
          ? "/budget/settings"
          : "/budget";

  return (
    <nav className="budget-tabs" aria-label="Budget sections">
      {tabs.map((tab) => (
        <Link className={tab.href === activeHref ? "active" : ""} href={tab.href} key={tab.href}>
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
