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

// The Home Nudges card's own, richer due-date line — always names the actual
// weekday (or weekday + day/month for anything past tomorrow), never a bare
// ISO date. Deliberately a separate function from routineDueLabel() above:
// that one's plain "Overdue"/"Today"/"Tomorrow"/raw-ISO output is still
// relied on by People and Settings > Routines & Reminders (see
// routine-utils.test.ts), which this card must not change the wording of.
// Parses the ISO date with an explicit local (no "Z") time so the weekday
// Intl.DateTimeFormat reads off matches the same local calendar day
// localIsoDate()/routineDueLabel() already reason about — never UTC, for the
// same reason documented at the top of this file.
export function nudgeCardDateLabel(
  homeOccurrenceDate: string | null | undefined,
  today: string = localIsoDate(),
): string {
  if (!homeOccurrenceDate) return "Scheduled";
  const date = new Date(`${homeOccurrenceDate}T00:00:00`);
  const weekday = new Intl.DateTimeFormat("en-GB", { weekday: "long" }).format(date);
  if (homeOccurrenceDate === today) return `Today · ${weekday}`;
  if (homeOccurrenceDate === addIsoDays(today, 1)) return `Tomorrow · ${weekday}`;
  const dayMonth = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(date);
  if (homeOccurrenceDate < today) return `Overdue · ${weekday} · ${dayMonth}`;
  return `${weekday} · ${dayMonth}`;
}
