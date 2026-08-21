"use client";

import { useMemo } from "react";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { resolveColour } from "@mykhaya/design-tokens";
import { usePrefersReducedMotion, useMonthSwipe } from "./use-month-swipe";
import {
  addMonths,
  dateKey,
  displayDate,
  eventDateBounds,
  eventTime,
  monthCells,
  zonedDateKey,
} from "./calendar-utils";

// Wraps MonthView with swipe-to-navigate: a horizontal drag "peeks" at the
// adjacent month (a plain MonthView rendered with that month's own cells,
// same component, no separate rendering path) and, past the gesture
// threshold, hands off to the exact same `onNavigate` the Previous/Next
// buttons already use — see move() in calendar/page.tsx. No swipe-specific
// month/focus state exists anywhere; useMonthSwipe only ever drives a CSS
// transform on the track, never React state, so a drag can't get out of
// sync with the real focusDate.
export function MonthSwipeView({
  cells,
  events,
  focusDate,
  timeZone,
  onDay,
  onEvent,
  onNavigate,
}: {
  cells: Date[];
  events: EventOccurrence[];
  focusDate: Date;
  timeZone: string;
  onDay: (day: Date) => void;
  onEvent: (event: EventOccurrence) => void;
  onNavigate: (direction: -1 | 1) => void;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const { trackRef, containerHandlers } = useMonthSwipe({
    onSwipeLeft: () => onNavigate(1),
    onSwipeRight: () => onNavigate(-1),
    reducedMotion,
  });
  // Adjacent months' events aren't separately fetched (the existing month
  // fetch already pads its range to cover the leading/trailing days visible
  // in this month's own grid — see fetchRange in calendar/page.tsx) —
  // passing the same `events` list here costs nothing extra and correctly
  // shows whatever overlap already loaded, rather than firing new API calls.
  const previousDate = useMemo(() => addMonths(focusDate, -1), [focusDate]);
  const nextDate = useMemo(() => addMonths(focusDate, 1), [focusDate]);
  const previousCells = useMemo(() => monthCells(previousDate), [previousDate]);
  const nextCells = useMemo(() => monthCells(nextDate), [nextDate]);

  return (
    <div className="calendar-month-swipe" {...containerHandlers}>
      <div className="calendar-month-swipe-track" ref={trackRef}>
        <div className="calendar-month-swipe-panel" aria-hidden="true">
          <MonthView
            cells={previousCells}
            events={events}
            focusDate={previousDate}
            timeZone={timeZone}
            onDay={onDay}
            onEvent={onEvent}
          />
        </div>
        <div className="calendar-month-swipe-panel">
          <MonthView
            cells={cells}
            events={events}
            focusDate={focusDate}
            timeZone={timeZone}
            onDay={onDay}
            onEvent={onEvent}
          />
        </div>
        <div className="calendar-month-swipe-panel" aria-hidden="true">
          <MonthView
            cells={nextCells}
            events={events}
            focusDate={nextDate}
            timeZone={timeZone}
            onDay={onDay}
            onEvent={onEvent}
          />
        </div>
      </div>
    </div>
  );
}

// Show at most this many event bars per week before collapsing the rest into a
// "+N more" indicator — a week with nothing more than this stays compact instead of
// reserving space for events it doesn't have.
const MONTH_VISIBLE_ROW_CAP = 3;

export function MonthView({
  cells,
  events,
  focusDate,
  timeZone,
  onDay,
  onEvent,
}: {
  cells: Date[];
  events: EventOccurrence[];
  focusDate: Date;
  timeZone: string;
  onDay: (day: Date) => void;
  onEvent: (event: EventOccurrence) => void;
}) {
  const todayKey = zonedDateKey(new Date(), timeZone);
  const bounds = useMemo(
    () => new Map(events.map((event) => [event.occurrence_id, eventDateBounds(event, timeZone)])),
    [events, timeZone],
  );
  return (
    <section className="calendar-month" aria-label="Month view">
      <div className="calendar-weekdays" aria-hidden="true">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label) => <span key={label}>{label}</span>)}
      </div>
      <div className="calendar-weeks">
        {Array.from({ length: 6 }, (_, weekIndex) => {
          const days = cells.slice(weekIndex * 7, weekIndex * 7 + 7);
          const weekStart = dateKey(days[0]!);
          const weekEnd = dateKey(days[6]!);
          const rows: { event: EventOccurrence; start: number; end: number; row: number }[] = [];
          const rowIntervals: { start: number; end: number }[][] = [];
          events
            .filter((event) => {
              const { startKey, endKey } = bounds.get(event.occurrence_id)!;
              return endKey >= weekStart && startKey <= weekEnd;
            })
            .sort((a, b) => bounds.get(a.occurrence_id)!.startKey.localeCompare(bounds.get(b.occurrence_id)!.startKey) || a.title.localeCompare(b.title))
            .forEach((event) => {
              const { startKey, endKey } = bounds.get(event.occurrence_id)!;
              const start = Math.max(0, days.findIndex((day) => dateKey(day) >= startKey));
              const end = Math.min(6, days.reduce((last, day, index) => dateKey(day) <= endKey ? index : last, -1));
              if (end < start) return;
              let row = rowIntervals.findIndex((intervals) => intervals.every((interval) => end < interval.start || start > interval.end));
              if (row === -1) row = rowIntervals.length;
              (rowIntervals[row] ??= []).push({ start, end });
              rows.push({ event, start, end, row });
            });
          const hiddenByDay = days.map((day) => rows.filter((item) => item.row >= MONTH_VISIBLE_ROW_CAP && item.start <= days.indexOf(day) && item.end >= days.indexOf(day)).length);
          // The whole point: a week with 0-1 events only reserves 0-1 event-row
          // tracks, not a fixed 4-row block every week gets regardless of content.
          const visibleRowCount = Math.min(rowIntervals.length, MONTH_VISIBLE_ROW_CAP);
          return (
            <div
              className="calendar-week"
              key={weekStart}
              style={{ gridTemplateRows: `var(--month-day-number-h) repeat(${visibleRowCount}, var(--month-event-row-h))` }}
            >
              {days.map((day, index) => {
                const key = dateKey(day);
                const count = events.filter((event) => {
                  const { startKey, endKey } = bounds.get(event.occurrence_id)!;
                  return startKey <= key && endKey >= key;
                }).length;
                const hidden = hiddenByDay[index] ?? 0;
                return (
                  <article
                    className={`calendar-day${key === todayKey ? " today" : ""}${day.getUTCMonth() !== focusDate.getUTCMonth() ? " outside" : ""}${index === 6 ? " sunday" : ""}`}
                    key={key}
                    style={{ gridColumn: index + 1, gridRow: "1 / -1" }}
                  >
                    <button className="day-number" type="button" onClick={() => onDay(day)} aria-label={`${displayDate(day, { weekday: "long", day: "numeric", month: "long", year: "numeric" }, "UTC")}, ${count} events`}>
                      <span>{day.getUTCDate()}</span>
                    </button>
                    {hidden > 0 && <button className="overflow-events" type="button" onClick={() => onDay(day)}>+{hidden} more</button>}
                  </article>
                );
              })}
              {rows.filter((item) => item.row < MONTH_VISIBLE_ROW_CAP).map(({ event, start, end, row }) => {
                // A multi-day event keeps the same solid-bar treatment on every week
                // segment it touches, even a segment that only covers one day of that
                // week (e.g. an event ending on a week's first day) — styling must key
                // off the event's own duration, not how much of it happens to fall in
                // this particular week, or a continuation segment would silently revert
                // to the lighter single-day chip look and read as a different event.
                const { startKey, endKey } = bounds.get(event.occurrence_id)!;
                const isMultiDay = endKey !== startKey;
                const segmentDays = end - start + 1;
                const isContinuation = startKey < weekStart;
                // A segment too narrow for its title to read as anything but a
                // meaningless fragment ("Te…", "0…") shows no text at all — a blank
                // coloured bar still communicates "this event continues here," which a
                // squeezed fragment does not.
                const showTitle = !isMultiDay || segmentDays >= 2;
                return (
                  <button
                    key={`${event.occurrence_id}-${weekStart}`}
                    type="button"
                    className={`month-event${isMultiDay ? " month-event-span" : ""}`}
                    style={
                      {
                        "--event-color": resolveColour(event.label?.color ?? event.calendar_color),
                        gridColumn: `${start + 1} / ${end + 2}`,
                        gridRow: row + 2,
                      } as React.CSSProperties
                    }
                    onClick={() => onEvent(event)}
                    aria-label={`${eventTime(event, timeZone)} ${event.title}`}
                    title={event.title}
                  >
                    {!isMultiDay && <span aria-hidden="true" />}
                    {showTitle ? `${isContinuation ? "↳ " : ""}${event.title}` : ""}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
  );
}
