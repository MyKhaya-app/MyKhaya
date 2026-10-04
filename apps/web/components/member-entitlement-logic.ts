// Pure display logic for the People/Home commercial-entitlement UI — mirrors
// calendar-entitlement-logic.ts's shape (same generic CalendarUsage —
// count/limit/over_limit — reused for home.max_members). Kept separate from
// rendering per this repo's convention.

import type { CalendarUsage } from "@mykhaya/shared-types";

export function canAddMember(usage: CalendarUsage): boolean {
  return usage.limit === null || usage.count < usage.limit;
}

/** The banner shown next to a disabled/blocked "Add member"/"Invite family"
 * action once a Free Home is at its member limit. Never mentions a price —
 * Plan & Billing owns pricing. */
export function memberLimitMessage(usage: CalendarUsage): string | null {
  if (canAddMember(usage)) return null;
  const count = usage.limit ?? usage.count;
  return `Your Home currently supports ${count} person${count === 1 ? "" : "s"} on the Free plan.`;
}

/** The Settings -> Plan & Billing explanation for a Home that currently has
 * more members than its plan allows (the result of a downgrade after
 * inviting people while on Family). Never shown for a Home within its
 * limit; never removes or suspends anyone. */
export function memberOverLimitExplanation(usage: CalendarUsage): string | null {
  if (!usage.over_limit) return null;
  const planWord = usage.limit === 1 ? "person" : "people";
  return (
    `Your Home has ${usage.count} people. The Free plan includes ${usage.limit} ${planWord}. ` +
    "Everyone's access is safe. Upgrade to Family to invite more household members."
  );
}
