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
  const activeHref = tabs.find((tab) => tab.href === pathname)?.href ?? "/budget";

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
