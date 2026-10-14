"use client";

import Link from "next/link";
import { featureEnabled, useHomeAccess } from "@/components/home-access";

// Shown when the Budget API refuses the Home. The API remains the access
// boundary; the shared plan/feature state only chooses the explanation, using
// the same wording and action as Driveway's gate for the same situations.
export function BudgetUnavailable() {
  const { access } = useHomeAccess();
  if (access.state === "loading") return <p role="status">Loading Budget…</p>;
  const resolved = access.state === "ready" ? access.value : null;
  if (resolved && !featureEnabled(resolved.features, "budget")) {
    return (
      <div className="budget-empty-state">
        <h1>Budget</h1>
        <p>Budget isn&apos;t available for this Home yet. Please check back soon.</p>
      </div>
    );
  }
  if (resolved && !resolved.billing.budget_enabled) {
    return (
      <div className="budget-empty-state">
        <h1>Budget</h1>
        <p>Included with MyKhaya Ultimate.</p>
        <Link className="button secondary" href="/settings/billing">
          View plans
        </Link>
      </div>
    );
  }
  return (
    <div className="budget-empty-state">
      <p className="budget-eyebrow">Budget</p>
      <h1>Budget isn’t available here</h1>
      <p>This Home has not enabled Budget. Ask a Home Admin to enable it before opening this page.</p>
    </div>
  );
}
