"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { MealPlanEntry, MealSlot } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";

// The Home screen's "smallest clean integration" for Meal Plans (see
// docs/architecture/meal-plans.md) — deliberately a small, self-contained
// component that owns its own data, rather than threading more state
// through the already-large Home page. Renders nothing at all for a Home
// without the Meal Plans entitlement/feature, exactly like the rest of
// Home already does for calendar-gated content.
//
// Shows every meal-plan entry for today (not just Dinner) — a household may
// have Breakfast, Lunch and/or Dinner planned for the same day, and the
// card should reflect all of them, in that order.

const SLOT_ORDER: { key: MealSlot; label: string }[] = [
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" },
];

// Mirrors meal-plans/page.tsx's isoToday()/entryTitle() — a plain
// wall-clock calendar date (the browser's local date, never UTC or the
// server's timezone) and the same meal_name/quick_meal_name fallback used
// throughout Meal Plans, so "today" and a meal's display name always agree
// with what the Meal Plans page itself would show.
function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function entryTitle(entry: MealPlanEntry): string {
  return entry.meal_name ?? entry.quick_meal_name ?? "Meal";
}

export function MealPlansTodayCard({ homeId }: { homeId: string }) {
  const [enabled, setEnabled] = useState(false);
  const [todayEntries, setTodayEntries] = useState<MealPlanEntry[]>([]);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api
      .billingStatus(homeId)
      .then(async (billing) => {
        setEnabled(billing.meals_enabled);
        if (!billing.meals_enabled) return;
        const day = await api.mealPlanDay(homeId, todayIso());
        setTodayEntries(day.entries);
      })
      .catch(() => setEnabled(false))
      .finally(() => setChecked(true));
  }, [homeId]);

  if (!checked || !enabled || todayEntries.length === 0) return null;

  const mealsBySlot = SLOT_ORDER.map((slot) => ({
    slot,
    entry: todayEntries.find((entry) => entry.meal_slot === slot.key),
  })).filter((row): row is { slot: (typeof SLOT_ORDER)[number]; entry: MealPlanEntry } =>
    Boolean(row.entry),
  );

  return (
    <section className="card home-section">
      <div className="section-heading">
        <h2>Meals</h2>
        <Link className="tertiary" href="/meal-plans">
          View meal plan
        </Link>
      </div>
      <div className="meal-today-list">
        {mealsBySlot.map(({ slot, entry }) => (
          <p className="meal-today-summary" key={slot.key}>
            <span>{slot.label}</span>
            <strong> · {entryTitle(entry)}</strong>
            {entry.time && <span> · {entry.time.slice(0, 5)}</span>}
            {entry.member_ids.length > 0 && <span> · {entry.member_ids.length} eating</span>}
          </p>
        ))}
      </div>
    </section>
  );
}
