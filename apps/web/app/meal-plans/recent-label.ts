// "Recently used" labels for Meal Plans. The API reports the latest date each
// meal is planned for, which is in the future when the meal is already on an
// upcoming plan, so the label has to distinguish past, today and future
// rather than treating every non-past date as "Today".

const DAY_MS = 86_400_000;

// Both dates are anchored at UTC midnight: comparing "now" (any time of day)
// against a date's UTC midnight would round today itself to "Yesterday" once
// the clock passes noon UTC — the same convention addDays/startOfWeek use.
export function daysFromToday(iso: string, todayIso: string): number {
  const today = new Date(`${todayIso}T00:00:00Z`).getTime();
  const then = new Date(`${iso}T00:00:00Z`).getTime();
  return Math.round((then - today) / DAY_MS);
}

function weeksPhrase(days: number): string {
  const weeks = Math.round(days / 7);
  return `${weeks} week${weeks === 1 ? "" : "s"}`;
}

export function recentPlannedLabel(iso: string, todayIso: string): string {
  const days = daysFromToday(iso, todayIso);
  if (days === 0) return "Planned for today";
  if (days === 1) return "Planned for tomorrow";
  if (days > 1) return days < 14 ? `Planned in ${days} days` : `Planned in ${weeksPhrase(days)}`;
  const ago = -days;
  if (ago === 1) return "Last planned Yesterday";
  if (ago < 14) return `Last planned ${ago} days ago`;
  return `Last planned ${weeksPhrase(ago)} ago`;
}
