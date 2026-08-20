"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { MealPlanEntry } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";

// The Home screen's "smallest clean integration" for Meal Plans (see
// docs/architecture/meal-plans.md) — deliberately a small, self-contained
// component that owns its own data, rather than threading more state
// through the already-large Home page. Renders nothing at all for a Home
// without the Meal Plans entitlement/feature, exactly like the rest of
// Home already does for calendar-gated content.

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function MealPlansTonightCard({ homeId }: { homeId: string }) {
  const [enabled, setEnabled] = useState(false);
  const [dinner, setDinner] = useState<MealPlanEntry | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api
      .billingStatus(homeId)
      .then(async (billing) => {
        setEnabled(billing.meals_enabled);
        if (!billing.meals_enabled) return;
        const day = await api.mealPlanDay(homeId, todayIso());
        setDinner(day.entries.find((entry) => entry.meal_slot === "dinner") ?? null);
      })
      .catch(() => setEnabled(false))
      .finally(() => setChecked(true));
  }, [homeId]);

  if (!checked || !enabled) return null;

  return (
    <section className="card home-section">
      <div className="section-heading">
        <h2>Tonight</h2>
        <Link className="tertiary" href="/meal-plans">
          View meal plan
        </Link>
      </div>
      {dinner ? (
        <p className="meal-tonight-summary">
          <strong>{dinner.meal_name ?? dinner.quick_meal_name}</strong>
          {dinner.time && <span> · {dinner.time.slice(0, 5)}</span>}
          {dinner.member_ids.length > 0 && <span> · {dinner.member_ids.length} eating</span>}
        </p>
      ) : (
        <>
          <p className="empty-mini">Nothing planned yet.</p>
          <Link className="button secondary" href="/meal-plans">
            Plan dinner
          </Link>
        </>
      )}
    </section>
  );
}
