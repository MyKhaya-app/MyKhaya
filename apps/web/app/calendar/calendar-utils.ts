import type { EventOccurrence } from "@mykhaya/shared-types";

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
  const start = dayRange(base).start;
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
