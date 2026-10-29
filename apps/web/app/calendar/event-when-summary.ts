import type { EventOccurrence } from "@mykhaya/shared-types";
import { dateKey, displayDate, zonedDateKey } from "./calendar-utils";

// The read-only View mode's date/time line — reuses the exact same
// timezone-correct display utilities as every other calendar view (never a
// separate UTC/browser-local/naive formatting path). All-day boundaries are
// read as plain UTC calendar dates (never re-localized); timed instants are
// read in the event's own governing timezone.
export function eventWhenSummary(
  event: EventOccurrence,
  timeZone: string,
): { dateLine: string; timeLine: string | null } {
  const tz = event.timezone || timeZone;
  const dateOptions: Intl.DateTimeFormatOptions = {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  };
  if (event.is_all_day) {
    const endInclusive = new Date(event.end_at);
    endInclusive.setUTCDate(endInclusive.getUTCDate() - 1);
    const startKey = dateKey(event.start_at);
    const endKey = dateKey(endInclusive);
    const dateLine =
      startKey === endKey
        ? displayDate(event.start_at, dateOptions, "UTC")
        : `${displayDate(event.start_at, dateOptions, "UTC")} — ${displayDate(endInclusive, dateOptions, "UTC")}`;
    return { dateLine, timeLine: "All day" };
  }
  const sameDay = zonedDateKey(event.start_at, tz) === zonedDateKey(event.end_at, tz);
  const startTimeLabel = displayDate(event.start_at, { hour: "2-digit", minute: "2-digit" }, tz);
  const endTimeLabel = displayDate(event.end_at, { hour: "2-digit", minute: "2-digit" }, tz);
  if (sameDay) {
    return {
      dateLine: displayDate(event.start_at, dateOptions, tz),
      timeLine: `${startTimeLabel} – ${endTimeLabel}`,
    };
  }
  return {
    dateLine: `${displayDate(event.start_at, dateOptions, tz)} ${startTimeLabel} → ${displayDate(event.end_at, dateOptions, tz)} ${endTimeLabel}`,
    timeLine: null,
  };
}
