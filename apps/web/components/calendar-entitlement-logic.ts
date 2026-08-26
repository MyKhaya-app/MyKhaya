// Pure display logic for calendar commercial-entitlement UI (Phase 6) — kept
// separate from rendering per this repo's convention (see billing-logic.ts).
// Every decision here is derived from backend-provided state
// (HomeCalendar.commercial_access, CalendarUsage) — nothing here re-derives
// which calendar is "the one that stays normal" itself; that's the
// backend's job (mykhaya.entitlements.classify_ordered_resources), so this
// module never needs to know about primary/created_at ordering.

import type { CalendarUsage, HomeCalendar } from "@mykhaya/shared-types";

export function canCreateCalendar(usage: CalendarUsage): boolean {
  return usage.limit === null || usage.count < usage.limit;
}

export function calendarBadgeLabel(calendar: HomeCalendar): string | null {
  return calendar.commercial_access === "read_only_due_to_plan" ? "Read-only on Free" : null;
}

export function calendarIsWritable(calendar: HomeCalendar): boolean {
  return calendar.commercial_access === "normal";
}

/** The banner shown next to a disabled/blocked "Add a Home calendar" action
 * once a Free Home is at its limit. Never mentions a price — Plan & Billing
 * owns pricing. This is about the count of Home *calendars* (e.g. a second
 * one like "GFOAT") — a distinct limit from how many Calendar Tags a Home
 * may have, even though both happen to share the same backend entitlement
 * key (calendar.max_categories, a naming legacy predating the Calendar vs
 * Calendar Tag split — see docs/architecture/commercial-entitlements.md
 * #event-categories). Customer-facing wording must say "calendar", never
 * "category"/"Calendar Tag", to avoid exactly that historical confusion. */
export function atLimitMessage(usage: CalendarUsage): string | null {
  if (canCreateCalendar(usage)) return null;
  const count = usage.limit ?? usage.count;
  return `You've reached the Free plan limit of ${count} Home calendar${count === 1 ? "" : "s"}.`;
}

/** The Settings -> Plan & Billing explanation for a Home that currently has
 * more Home calendars than its plan allows (almost always the result of a
 * downgrade — see docs/architecture/commercial-entitlements.md#event-categories).
 * Never shown for a Home within its limit. */
/** Whether this Home's plan currently allows creating a new external
 * Calendar Share (mykhaya.routers.calendar_sharing) — the calendars page
 * uses this to show the Family upsell before submission rather than only
 * after a 403. Receiving/accepting a share is never gated this way — see
 * BillingStatus.external_invites_enabled's docstring on why the name
 * predates this feature. */
export function canShareCalendar(externalInvitesEnabled: boolean): boolean {
  return externalInvitesEnabled;
}

export function overLimitExplanation(usage: CalendarUsage): string | null {
  if (!usage.over_limit) return null;
  const planWord = usage.limit === 1 ? "calendar" : "calendars";
  return (
    `Your Home has ${usage.count} Home calendars. The Free plan includes ${usage.limit} ${planWord}. ` +
    "Your calendars and events are safe. Upgrade to Family to restore full access to all of them."
  );
}
