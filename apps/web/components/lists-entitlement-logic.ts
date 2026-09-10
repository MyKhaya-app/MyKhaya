// Pure display logic for Lists commercial-entitlement UI (Phase 2B) — kept
// separate from rendering per this repo's convention (see
// calendar-entitlement-logic.ts, which this mirrors exactly for Lists'
// identical "preserve on downgrade, lock the excess" shape).

import type { CalendarUsage, HouseholdList } from "@mykhaya/shared-types";

export function canCreateList(usage: CalendarUsage): boolean {
  return usage.limit === null || usage.count < usage.limit;
}

export function listBadgeLabel(list: HouseholdList): string | null {
  return list.commercial_access === "read_only_due_to_plan" ? "Read-only on Free" : null;
}

export function listIsWritable(list: HouseholdList): boolean {
  return list.commercial_access === "normal";
}

/** The banner shown next to a disabled/blocked "Add a list" action once a
 * Free Home is at its lists.max_lists limit. Never mentions a price — Plan
 * & Billing owns pricing. */
export function atListLimitMessage(usage: CalendarUsage): string | null {
  if (canCreateList(usage)) return null;
  const count = usage.limit ?? usage.count;
  return `You've reached the Free plan limit of ${count} list${count === 1 ? "" : "s"}.`;
}
