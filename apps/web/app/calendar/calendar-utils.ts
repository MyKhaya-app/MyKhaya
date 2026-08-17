import type { EventOccurrence, Member } from "@mykhaya/shared-types";

export function dateKey(value: Date | string): string {
  return (typeof value === "string" ? value : value.toISOString()).slice(0, 10);
}

export function monthRange(base: Date) {
  return {
    start: new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1)),
    end: new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 1)),
  };
}

export function weekRange(base: Date) {
  const offset = (base.getUTCDay() + 6) % 7;
  const start = new Date(
    Date.UTC(
      base.getUTCFullYear(),
      base.getUTCMonth(),
      base.getUTCDate() - offset,
    ),
  );
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 7);
  return { start, end };
}

export function dayRange(base: Date) {
  const start = new Date(
    Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate()),
  );
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 1);
  return { start, end };
}

export function agendaRange(base: Date) {
  // Anchored to the start of the browsed month (same as monthRange) rather than
  // `base` itself, so Schedule always covers at least everything Month view shows
  // for the period the user is looking at — switching Month -> Schedule must not
  // silently drop events that are still within the visible month just because
  // they fall before "today" (or before `base`'s exact day). The +45 day
  // extension keeps the "look ahead" agenda behaviour beyond the current month.
  const start = monthRange(base).start;
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 45);
  return { start, end };
}

export function monthCells(base: Date): Date[] {
  const start = monthRange(base).start;
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setUTCDate(day.getUTCDate() + index);
    return day;
  });
}

export function eventsForDay(
  events: EventOccurrence[],
  day: Date | string,
): EventOccurrence[] {
  const target = dateKey(day);
  return events
    .filter((event) => {
      const start = dateKey(event.start_at);
      const endDate = new Date(event.end_at);
      if (!event.is_all_day || !event.end_at.endsWith("T00:00:00+00:00")) {
        return start <= target && dateKey(endDate) >= target;
      }
      endDate.setUTCDate(endDate.getUTCDate() - 1);
      return start <= target && dateKey(endDate) >= target;
    })
    .sort((left, right) => {
      if (left.is_all_day !== right.is_all_day) return left.is_all_day ? -1 : 1;
      return (
        left.start_at.localeCompare(right.start_at) ||
        left.title.localeCompare(right.title)
      );
    });
}

// Two independent, composable filters, applied in the same order and the same
// way regardless of which view (Month/Week/Day/Schedule) is rendering the
// resulting list, so all views stay in sync for a given selection:
//
// - `memberFilter` is a household member's stable user_id (the canonical
//   event-membership relationship, EventOccurrence.member_ids, backed by
//   CalendarEventMember) — "who is this event for", independent of who
//   created it. Empty string means no member filter ("Everyone").
// - `labelFilter` is a household-defined CalendarEventLabel id (a free-form
//   category/tag, e.g. "Family calendar", "Work", or a personal label someone
//   named after a household member such as "Megan") — a category filter, NOT
//   a participant/member filter, even when its name happens to match a
//   person's name. Empty string means no category filter.
export function filterVisibleEvents(
  events: EventOccurrence[],
  memberFilter: string,
  labelFilter: string,
  query: string,
): EventOccurrence[] {
  let filtered = memberFilter
    ? events.filter((event) => event.member_ids.includes(memberFilter))
    : events;
  filtered = labelFilter
    ? filtered.filter((event) => (event.label?.id ?? "") === labelFilter)
    : filtered;
  const needle = query.trim().toLowerCase();
  if (!needle) return filtered;
  return filtered.filter((event) => event.title.toLowerCase().includes(needle));
}

// A persisted member-filter selection is only trustworthy while it still
// names a real member of the *currently active* Home — a member who left,
// was deleted, or belongs to a different Home (persistence is home-scoped,
// see MEMBER_STORAGE_PREFIX in page.tsx, but this guards the load-race and
// deletion cases too) must fall back to "Everyone" rather than silently
// filtering the calendar down to nothing forever.
export function resolveMemberFilter(
  members: Member[],
  persisted: string,
): string {
  if (!persisted) return "";
  return members.some((member) => member.user_id === persisted) ? persisted : "";
}

// Empty-state copy for a filtered, otherwise-empty list. Deliberately simple
// (member clause, then category clause) rather than generating full
// sentences for every combination.
export function emptyStateMessage(
  memberName: string | null,
  labelName: string | null,
): string {
  const clauses = [
    memberName ? `for ${memberName}` : "",
    labelName ? `in ${labelName}` : "",
  ].filter(Boolean);
  if (clauses.length === 0) return "No upcoming events.";
  return `No upcoming events ${clauses.join(" ")}.`;
}

export function groupEventsByDay(
  events: EventOccurrence[],
): Map<string, EventOccurrence[]> {
  const result = new Map<string, EventOccurrence[]>();
  for (const event of events) {
    const start = new Date(`${dateKey(event.start_at)}T00:00:00.000Z`);
    const end = new Date(`${dateKey(event.end_at)}T00:00:00.000Z`);
    if (event.is_all_day && event.end_at.includes("T00:00:00"))
      end.setUTCDate(end.getUTCDate() - 1);
    for (
      const cursor = new Date(start);
      cursor <= end;
      cursor.setUTCDate(cursor.getUTCDate() + 1)
    ) {
      const key = dateKey(cursor);
      result.set(key, eventsForDay([...(result.get(key) ?? []), event], key));
    }
  }
  return result;
}
