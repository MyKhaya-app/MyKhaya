import type { BirthdayEntry } from "@mykhaya/shared-types";

const BIRTHDAY_MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Birth month/day only (never the stored birth year — MyKhaya never calculates or
// shows age). Reconstructed against *this* calendar year rather than trusting
// next_occurrence_date, which resolves to next year once the date has passed —
// this keeps "this month" filtering correct across the Dec -> Jan boundary.
export function daysUntilThisYear(entry: BirthdayEntry, now: Date = new Date()) {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const target = new Date(today.getFullYear(), entry.month - 1, entry.day);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function isBirthdayThisMonthAndUpcoming(entry: BirthdayEntry, now: Date = new Date()) {
  return entry.month === now.getMonth() + 1 && daysUntilThisYear(entry, now) >= 0;
}

export function birthdayDateLabel(entry: BirthdayEntry) {
  return `${entry.day} ${BIRTHDAY_MONTH_NAMES[entry.month - 1]}`;
}

export function upcomingBirthdayLabel(days: number) {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

export function upcomingBirthdayIcon(days: number) {
  if (days === 0) return "🎉";
  if (days <= 7) return "🎁";
  return "🎂";
}
