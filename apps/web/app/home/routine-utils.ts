// Local-calendar-date helpers for the Home "To do" card's routine rows —
// mirrors birthday-utils.ts's injectable-`now` pattern so both stay
// independently testable. Deliberately built on Date's local getters
// (getFullYear/getMonth/getDate), never `toISOString()` — an ISO string is
// always UTC, so slicing it can land a routine's due-date label ("Overdue"
// vs "Today" vs "Tomorrow") on the wrong side of midnight for any Home not
// in UTC. Matches the same todayIso() convention already used by
// meal-plans/page.tsx, meal-plans-today-card.tsx and settings/routines/page.tsx.

export function localIsoDate(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function addIsoDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// `today` defaults to the caller's local date but takes an explicit value so
// the label logic itself can be tested without touching the system clock.
export function routineDueLabel(
  homeOccurrenceDate: string | null | undefined,
  today: string = localIsoDate(),
): string {
  if (!homeOccurrenceDate) return "Scheduled";
  if (homeOccurrenceDate < today) return "Overdue";
  if (homeOccurrenceDate === today) return "Today";
  if (homeOccurrenceDate === addIsoDays(today, 1)) return "Tomorrow";
  return homeOccurrenceDate;
}
