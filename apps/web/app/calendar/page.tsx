"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Layers,
  Plus,
  Search,
  X,
} from "lucide-react";
import type {
  BirthdayEntry,
  EventLabel,
  EventOccurrence,
  EventPayload,
  Member,
  RecurrencePattern,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { resolveColour } from "@mykhaya/design-tokens";
import { AppShell } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { useActiveHome } from "@/components/use-active-home";
import {
  agendaRange,
  applyAllDayToggle,
  computeInitialWhen,
  DEFAULT_EVENT_DURATION_MINUTES,
  dateKey,
  dayRange,
  emptyStateMessage,
  eventDateBounds,
  eventsForDay,
  FALLBACK_TIMEZONE,
  filterVisibleEvents,
  groupEventsByDay,
  monthCells,
  monthRange,
  parseLocalInputValue,
  resolveMemberFilter,
  shiftEndWithStart,
  splitZoned,
  weekRange,
  zonedDateKey,
  zonedTimeToUtc,
  zonedToday,
} from "./calendar-utils";

type ViewMode = "month" | "week" | "day" | "agenda";
const VIEW_STORAGE = "mykhaya.calendar.view";
const LABEL_STORAGE = "mykhaya.calendar.label";
// Home-scoped so a member selection never leaks from one Home to another —
// switching Home must never accidentally keep filtering by a member id that
// only means something in the Home the user just left.
const MEMBER_STORAGE_PREFIX = "mykhaya.calendar.member.";

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

// `timeZone` must always be passed explicitly — the calendar grid's active
// timezone (the Home's primary calendar timezone) for headers/day labels, or
// an individual event's own governing timezone (event.timezone) when
// formatting that event's time. Never the browser's local zone, never a
// hardcoded UTC default: the server/browser timezone must never leak into
// what a user sees.
function displayDate(
  value: Date | string,
  options: Intl.DateTimeFormatOptions,
  timeZone: string,
) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    ...options,
  }).format(typeof value === "string" ? new Date(value) : value);
}

function eventTime(event: EventOccurrence, timeZone: string) {
  if (event.is_all_day) return "All day";
  return displayDate(
    event.start_at,
    { hour: "2-digit", minute: "2-digit" },
    event.timezone || timeZone,
  );
}

function relativeDayHeading(key: string, timeZone: string) {
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  if (key === zonedDateKey(now, timeZone)) return "Today";
  if (key === zonedDateKey(tomorrow, timeZone)) return "Tomorrow";
  return displayDate(
    `${key}T00:00:00Z`,
    { weekday: "long", day: "numeric", month: "long" },
    "UTC",
  );
}

function combineZoned(date: string, time: string, timeZone: string): Date {
  const { year, month, day } = parseLocalInputValue(date);
  const [hour, minute] = time.split(":").map(Number);
  return zonedTimeToUtc(year, month, day, hour ?? 0, minute ?? 0, timeZone);
}

// A pure UTC-midnight calendar date, independent of any timezone — see
// `_all_day_midnight` on the backend for why all-day boundaries deliberately
// never go through zone conversion.
function utcMidnightOf(dateInput: string): Date {
  const { year, month, day } = parseLocalInputValue(dateInput);
  return new Date(Date.UTC(year, month - 1, day));
}

function EventForm({
  labels,
  members,
  initial,
  initialDay,
  timeZone,
  busy,
  submitLabel,
  sharedEventsEnabled,
  onSubmit,
  onCancel,
  onDelete,
}: {
  labels: EventLabel[];
  members: Member[];
  initial?: EventOccurrence;
  initialDay: Date;
  /** The IANA timezone new Start/End wall-clock values are interpreted in —
   *  the calendar's active (Home) timezone for a new event, or the event's
   *  own governing timezone when editing one that already has a different
   *  one set. Never the browser's local zone, never a hardcoded literal. */
  timeZone: string;
  busy: boolean;
  submitLabel: string;
  sharedEventsEnabled: boolean;
  onSubmit: (payload: EventPayload) => Promise<void>;
  onCancel: () => void;
  onDelete?: () => Promise<void>;
}) {
  const eventTimeZone = initial?.timezone || timeZone;
  const [initialWhen] = useState(() =>
    computeInitialWhen(initial, initialDay, eventTimeZone),
  );
  const [allDay, setAllDay] = useState(initialWhen.allDay);
  const [startDate, setStartDate] = useState(initialWhen.startDate);
  const [startTime, setStartTime] = useState(initialWhen.startTime);
  const [endDate, setEndDate] = useState(initialWhen.endDate);
  const [endTime, setEndTime] = useState(initialWhen.endTime);
  const [multiDay, setMultiDay] = useState(initialWhen.multiDay);
  const [rangeNotice, setRangeNotice] = useState("");
  // See WhenState.hasTimedValues — a ref, not state, because flipping it
  // must never itself trigger a render; it only gates what onToggleAllDay
  // does the next time the user actually turns All day off.
  const hasTimedValues = useRef(initialWhen.hasTimedValues);

  function zonedInstant(date: string, time: string): Date {
    return combineZoned(date, time, eventTimeZone);
  }

  // See applyAllDayToggle (calendar-utils.ts) for the rule this applies —
  // toggling All day off must never derive a clock value from the all-day
  // UTC-midnight boundary; it establishes a sensible default only once per
  // session, preserving whatever meaningful timed value already exists
  // otherwise (startDate/endDate — the intended calendar date(s) — are
  // untouched either way).
  function onToggleAllDay(nextAllDay: boolean) {
    const next = applyAllDayToggle(
      {
        allDay,
        startDate,
        startTime,
        endDate,
        endTime,
        multiDay,
        hasTimedValues: hasTimedValues.current,
      },
      nextAllDay,
    );
    setAllDay(next.allDay);
    setStartTime(next.startTime);
    setEndTime(next.endTime);
    hasTimedValues.current = next.hasTimedValues;
  }

  // Duration-aware: moving Start carries End along by the same duration
  // (defaulting new events to 1 hour, preserving whatever duration the user
  // has already established otherwise) — see shiftEndWithStart.
  function applyNewStart(nextStart: Date) {
    const previousStart = zonedInstant(startDate, startTime);
    const previousEnd = zonedInstant(endDate, endTime);
    const nextEnd = shiftEndWithStart(previousStart, previousEnd, nextStart);
    const next = splitZoned(nextEnd, eventTimeZone);
    setEndDate(next.date);
    setEndTime(next.time);
    setRangeNotice("");
  }

  function onStartDateChange(value: string) {
    setStartDate(value);
    if (!multiDay) setEndDate(value);
    applyNewStart(zonedInstant(value, startTime));
  }
  function onStartTimeChange(value: string) {
    setStartTime(value);
    applyNewStart(zonedInstant(startDate, value));
  }
  // End is user-editable directly too, but must never be allowed to precede
  // Start for a same-day event — corrected in place (kept to a sensible
  // minimum duration) rather than silently accepted and only rejected later
  // by the backend.
  function onEndDateChange(value: string) {
    const candidate = zonedInstant(value, endTime);
    const start = zonedInstant(startDate, startTime);
    if (candidate <= start) {
      setRangeNotice("End adjusted to stay after Start.");
      const corrected = new Date(start.getTime() + DEFAULT_EVENT_DURATION_MINUTES * 60_000);
      const next = splitZoned(corrected, eventTimeZone);
      setEndDate(next.date);
      setEndTime(next.time);
      return;
    }
    setRangeNotice("");
    setEndDate(value);
  }
  function onEndTimeChange(value: string) {
    const candidate = zonedInstant(endDate, value);
    const start = zonedInstant(startDate, startTime);
    if (!multiDay && candidate <= start) {
      setRangeNotice("End adjusted to stay after Start.");
      const corrected = new Date(start.getTime() + DEFAULT_EVENT_DURATION_MINUTES * 60_000);
      const next = splitZoned(corrected, eventTimeZone);
      setEndDate(next.date);
      setEndTime(next.time);
      return;
    }
    setRangeNotice("");
    setEndTime(value);
  }
  function onToggleMultiDay(next: boolean) {
    setMultiDay(next);
    if (!next) setEndDate(startDate);
    setRangeNotice("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const title = formText(data, "title").trim();

    let start_at: string;
    let end_at: string;
    if (allDay) {
      const start = utcMidnightOf(startDate);
      const lastCoveredDay = utcMidnightOf(multiDay ? endDate : startDate);
      const end = new Date(lastCoveredDay);
      end.setUTCDate(end.getUTCDate() + 1); // exclusive end, matching backend semantics
      start_at = start.toISOString();
      end_at = end.toISOString();
    } else {
      start_at = zonedInstant(startDate, startTime).toISOString();
      end_at = zonedInstant(multiDay ? endDate : startDate, endTime).toISOString();
    }

    await onSubmit({
      title,
      start_at,
      end_at,
      timezone: eventTimeZone,
      is_all_day: allDay,
      member_ids: data.getAll("members").map(String),
      label_id: formText(data, "label") || null,
      location_text: formText(data, "location") || null,
      reminder_minutes: formText(data, "reminder")
        ? Number(formText(data, "reminder"))
        : null,
      recurrence: (formText(data, "recurrence") || "none") as RecurrencePattern,
      recurrence_interval: 1,
      recurrence_until: null,
      recurrence_count: null,
      description: formText(data, "notes") || null,
    });
  }

  return (
    <form className="event-form" onSubmit={submit}>
      <label className="form-wide">
        Title
        <input
          name="title"
          defaultValue={initial?.title ?? ""}
          required
          maxLength={180}
        />
      </label>
      <fieldset className="form-wide event-when">
        <legend>When</legend>
        <label className="check-row">
          <input
            type="checkbox"
            checked={allDay}
            onChange={(event) => onToggleAllDay(event.target.checked)}
          />
          All day
        </label>
        <div className="event-when-grid">
          <label>
            {multiDay ? "Starts" : "Date"}
            <input
              type="date"
              value={startDate}
              onChange={(event) => onStartDateChange(event.target.value)}
              required
            />
          </label>
          {!allDay && (
            <label>
              Start
              <input
                type="time"
                value={startTime}
                onChange={(event) => onStartTimeChange(event.target.value)}
                required
              />
            </label>
          )}
          {!allDay && !multiDay && (
            <label>
              End
              <input
                type="time"
                value={endTime}
                onChange={(event) => onEndTimeChange(event.target.value)}
                required
              />
            </label>
          )}
        </div>
        {multiDay && (
          <div className="event-when-grid">
            <label>
              Ends
              <input
                type="date"
                value={endDate}
                onChange={(event) => onEndDateChange(event.target.value)}
                required
              />
            </label>
            {!allDay && (
              <label>
                End time
                <input
                  type="time"
                  value={endTime}
                  onChange={(event) => onEndTimeChange(event.target.value)}
                  required
                />
              </label>
            )}
          </div>
        )}
        <button
          type="button"
          className="link-button"
          onClick={() => onToggleMultiDay(!multiDay)}
        >
          {multiDay ? "Same day event" : "Ends on a different day"}
        </button>
        {rangeNotice && <p className="quiet-state">{rangeNotice}</p>}
      </fieldset>
      {members.length > 0 && (
        <fieldset className="form-wide">
          <legend>Household members</legend>
          <div className="member-checks">
            {members.map((member) => {
              // Assigning a *new* member is the Family-only "shared event"
              // capability (events.shared.enabled) — a member already on this
              // event stays freely toggleable (so removing one, or simply
              // re-saving other fields, always works) even on Free; only
              // checking a box for someone not already assigned is locked.
              // Disabling (rather than hiding) an already-checked box would
              // drop it from the submitted form data entirely, so this only
              // ever disables boxes that are unchecked to begin with.
              const alreadyIncluded = initial?.member_ids.includes(member.user_id) ?? false;
              const locked = !sharedEventsEnabled && !alreadyIncluded;
              return (
                <label
                  className={`check-row${locked ? " check-row-locked" : ""}`}
                  key={member.user_id}
                >
                  <input
                    name="members"
                    type="checkbox"
                    value={member.user_id}
                    defaultChecked={alreadyIncluded}
                    disabled={locked}
                  />
                  {member.display_name}
                  {locked && <span className="quiet-state"> · Family</span>}
                </label>
              );
            })}
          </div>
          {!sharedEventsEnabled && (
            <p className="quiet-state">
              Assigning this event to other household members is available with MyKhaya Family.
            </p>
          )}
        </fieldset>
      )}
      <label>
        Calendar or category
        <select name="label" defaultValue={initial?.label?.id ?? ""}>
          <option value="">Family calendar</option>
          {labels.map((label) => {
            // Transition-safe, matching update_event's own check: a category
            // already assigned to this event stays selectable (so resaving
            // never breaks), but a different, over-the-plan-limit category
            // preserved past a downgrade can't be newly assigned.
            const locked =
              label.commercial_access === "read_only_due_to_plan" &&
              initial?.label?.id !== label.id;
            return (
              <option key={label.id} value={label.id} disabled={locked}>
                {label.name}
                {locked ? " (Family)" : ""}
              </option>
            );
          })}
        </select>
      </label>
      <label>
        Location
        <input
          name="location"
          maxLength={200}
          defaultValue={initial?.location_text ?? ""}
        />
      </label>
      <details className="form-wide event-advanced">
        <summary>Reminder, repeat and notes</summary>
        <div className="event-form advanced-fields">
          <label>
            Reminder
            <select
              name="reminder"
              defaultValue={initial?.reminder_minutes ?? ""}
            >
              <option value="">None</option>
              <option value="0">At event time</option>
              <option value="15">15 minutes before</option>
              <option value="60">1 hour before</option>
              <option value="1440">1 day before</option>
            </select>
          </label>
          <label>
            Repeat
            <select
              name="recurrence"
              defaultValue={initial?.recurrence ?? "none"}
            >
              <option value="none">Does not repeat</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
              <option value="weekdays">Weekdays</option>
            </select>
          </label>
          <label className="form-wide">
            Notes
            <textarea
              name="notes"
              maxLength={2000}
              defaultValue={initial?.description ?? ""}
            />
          </label>
        </div>
      </details>
      <div className="sheet-actions form-wide">
        <button disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
        <button className="secondary" type="button" onClick={onCancel}>
          Cancel
        </button>
        {onDelete && (
          <button className="danger-link" type="button" onClick={onDelete}>
            Delete event
          </button>
        )}
      </div>
    </form>
  );
}

export default function CalendarPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { activeHome, activeHomeId } = useActiveHome();
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [featureChecked, setFeatureChecked] = useState(false);
  const [view, setView] = useState<ViewMode>("month");
  const [focusDate, setFocusDate] = useState(() => zonedToday(FALLBACK_TIMEZONE));
  // True once the user has actually navigated (prev/next, tapping a day, or
  // jumping to today) — until then, focusDate keeps re-anchoring to "today"
  // as soon as the real calendarTimezone loads, so the initial render (which
  // only has FALLBACK_TIMEZONE to go on) doesn't strand the user looking at
  // the wrong calendar date for their Home's actual timezone.
  const hasNavigated = useRef(false);
  const [events, setEvents] = useState<EventOccurrence[]>([]);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [sharedEventsEnabled, setSharedEventsEnabled] = useState(false);
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [editorDay, setEditorDay] = useState<Date | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<EventOccurrence | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [labelFilter, setLabelFilter] = useState("");
  const [memberFilter, setMemberFilter] = useState("");
  // The Home's primary calendar's IANA timezone — the default/shared
  // timezone for household calendar events (never the server's or the
  // browser's own timezone). FALLBACK_TIMEZONE only covers the brief window
  // before the first successful load.
  const [calendarTimezone, setCalendarTimezone] = useState(FALLBACK_TIMEZONE);

  useEffect(() => {
    setLabelFilter(window.localStorage.getItem(LABEL_STORAGE) ?? "");
  }, []);

  function chooseLabel(next: string) {
    setLabelFilter(next);
    window.localStorage.setItem(LABEL_STORAGE, next);
  }

  // Restore the previously selected household member for *this* Home as soon
  // as we know which Home is active, and re-restore whenever the active Home
  // changes — a stored id for Home A must never carry over when the user
  // switches to Home B.
  useEffect(() => {
    if (!activeHomeId) return;
    setMemberFilter(
      window.localStorage.getItem(MEMBER_STORAGE_PREFIX + activeHomeId) ?? "",
    );
  }, [activeHomeId]);

  function chooseMember(next: string) {
    setMemberFilter(next);
    if (activeHomeId)
      window.localStorage.setItem(MEMBER_STORAGE_PREFIX + activeHomeId, next);
  }

  // Guards against a persisted member id that no longer belongs to this
  // Home's roster (the member left, was deleted, or the id was left over
  // from a different Home) — falls back to "Everyone" rather than leaving
  // the calendar silently filtered to a member that can never match again.
  // `members` starts empty until the first load resolves, so this only acts
  // once a real roster is in hand.
  useEffect(() => {
    if (!memberFilter || members.length === 0) return;
    const resolved = resolveMemberFilter(members, memberFilter);
    if (resolved !== memberFilter) chooseMember(resolved);
  }, [members, memberFilter, activeHomeId]);

  useEffect(() => {
    const stored = window.localStorage.getItem(VIEW_STORAGE) as ViewMode | null;
    if (stored && ["month", "week", "day", "agenda"].includes(stored))
      setView(stored);
    else setView("month");
  }, []);

  function chooseView(next: ViewMode) {
    setView(next);
    window.localStorage.setItem(VIEW_STORAGE, next);
  }

  const range = useMemo(() => {
    if (view === "month") return monthRange(focusDate);
    if (view === "week") return weekRange(focusDate);
    if (view === "day") return dayRange(focusDate);
    return agendaRange(focusDate);
  }, [focusDate, view]);

  const cells = useMemo(() => monthCells(focusDate), [focusDate]);

  // Month view renders 6 weeks (42 cells) padded with days from the adjacent months,
  // but `range` above is the exact calendar month (1st to last day) — a multi-day
  // event that starts in the trailing days of last month or ends in the leading days
  // of next month, yet is still visible in the padded grid, was never fetched at all.
  // Fetch the full padded range for month view specifically; other views are
  // unaffected.
  const fetchRange = useMemo(() => {
    if (view !== "month") return range;
    const start = cells[0]!;
    const end = new Date(cells[cells.length - 1]!);
    end.setUTCDate(end.getUTCDate() + 1);
    return { start, end };
  }, [view, range, cells]);

  const load = useCallback(async () => {
    if (!activeHomeId || !featureEnabled) return;
    const [labelRows, eventRows, memberRows, calendarRows] = await Promise.all([
      api.listLabels(activeHomeId),
      api.listEvents(activeHomeId, {
        start_at: fetchRange.start.toISOString(),
        end_at: fetchRange.end.toISOString(),
        page_size: 300,
      }),
      api.members(activeHomeId).catch(() => []),
      api.listCalendars(activeHomeId).catch(() => null),
    ]);
    setLabels(labelRows);
    setEvents(eventRows.items);
    setMembers(memberRows);
    const primaryCalendar = calendarRows?.items.find((row) => row.is_primary);
    if (primaryCalendar) setCalendarTimezone(primaryCalendar.timezone);
    api
      .birthdays(activeHomeId)
      .then((response) => setBirthdays(response.items))
      .catch(() => setBirthdays([]));
  }, [activeHomeId, featureEnabled, fetchRange.end, fetchRange.start]);

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => setSharedEventsEnabled(billing.shared_events_enabled))
      .catch(() => setSharedEventsEnabled(false));
  }, [activeHomeId]);

  useEffect(() => {
    if (!activeHomeId) return;
    setFeatureChecked(false);
    api
      .featureMatrix(activeHomeId)
      .then((matrix) => {
        const enabled = matrix.features.some(
          (item) => item.feature === "calendar" && item.enabled,
        );
        setFeatureEnabled(enabled);
        setFeatureChecked(true);
        if (!enabled) router.replace("/home");
      })
      .catch(() => router.replace("/home"));
  }, [activeHomeId, router]);

  useEffect(() => {
    // Deep-linked from a reminder notification (?event=<id>) — open it directly rather
    // than requiring the user to find it in the calendar list. Independent of the
    // visible date range/view, since a reminder can point at an occurrence outside it.
    const deepLinkedEventId = searchParams.get("event");
    if (!activeHomeId || !deepLinkedEventId) return;
    api
      .eventDetail(activeHomeId, deepLinkedEventId)
      .then((detail) => setSelectedEvent(detail.event))
      .catch(() => {
        // The event may have been deleted since the reminder was sent — fail quietly,
        // the user just lands on the calendar with nothing pre-opened.
      });
  }, [activeHomeId, searchParams]);

  useEffect(() => {
    setError("");
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  const visibleEvents = useMemo(
    () => filterVisibleEvents(events, memberFilter, labelFilter, query),
    [events, memberFilter, labelFilter, query],
  );
  const byDay = useMemo(
    () => groupEventsByDay(visibleEvents, calendarTimezone),
    [visibleEvents, calendarTimezone],
  );
  const memberNames = useMemo(
    () =>
      new Map(members.map((member) => [member.user_id, member.display_name])),
    [members],
  );
  const selectedMemberName = memberFilter
    ? (memberNames.get(memberFilter) ?? null)
    : null;
  const selectedLabelName = labelFilter
    ? (labels.find((label) => label.id === labelFilter)?.name ?? null)
    : null;
  const scheduleEmptyMessage = emptyStateMessage(
    selectedMemberName,
    selectedLabelName,
  );

  // Re-anchor to "today" (in the Home calendar's real timezone) once it's
  // known — but only until the user actually navigates; see hasNavigated.
  useEffect(() => {
    if (!hasNavigated.current) setFocusDate(zonedToday(calendarTimezone));
  }, [calendarTimezone]);

  function move(direction: -1 | 1) {
    hasNavigated.current = true;
    const next = new Date(focusDate);
    if (view === "month") next.setUTCMonth(next.getUTCMonth() + direction);
    else if (view === "week")
      next.setUTCDate(next.getUTCDate() + direction * 7);
    else next.setUTCDate(next.getUTCDate() + direction);
    setFocusDate(next);
  }

  async function create(payload: EventPayload) {
    if (!activeHomeId) return;
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.createEvent(activeHomeId, payload);
      setEditorDay(null);
      setSelectedDay(null);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "We could not save your event.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function update(payload: EventPayload) {
    if (!activeHomeId || !selectedEvent) return;
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.updateEvent(activeHomeId, selectedEvent.event_id, {
        ...payload,
        expected_updated_at: selectedEvent.updated_at,
      });
      setSelectedEvent(null);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "This event changed. Reload and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !activeHomeId ||
      !selectedEvent ||
      !window.confirm("Delete this event?")
    )
      return;
    try {
      await api.deleteEvent(activeHomeId, selectedEvent.event_id);
      setSelectedEvent(null);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The event could not be deleted.",
      );
    }
  }

  function openDay(day: Date) {
    hasNavigated.current = true;
    setFocusDate(day);
    setSelectedDay(day);
  }

  if (!featureChecked || !featureEnabled) {
    return (
      <AppShell>
        <main className="standard-page">
          <p role="status">Checking Calendar access...</p>
        </main>
      </AppShell>
    );
  }

  const focusedEvents = eventsForDay(visibleEvents, focusDate, calendarTimezone);
  const birthdaysInRange = birthdays.filter((entry) => {
    const occurrence = new Date(entry.next_occurrence_date);
    return occurrence >= range.start && occurrence < range.end;
  });

  return (
    <AppShell>
      <main className="standard-page calendar-page">
        <header className="calendar-toolbar-compact">
          <div className="calendar-month-row">
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(-1)}
              aria-label="Previous period"
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <h1 className="calendar-month-label">
              {view === "day"
                ? displayDate(focusDate, { weekday: "short", day: "numeric", month: "short" }, "UTC")
                : displayDate(focusDate, { month: "long", year: "numeric" }, "UTC")}
            </h1>
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(1)}
              aria-label="Next period"
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
            <div className="calendar-month-row-actions">
              <button
                className="icon-button secondary"
                type="button"
                onClick={() => setFocusDate(zonedToday(calendarTimezone))}
                aria-label="Jump to today"
                title="Today"
              >
                <CalendarDays size={16} aria-hidden="true" />
              </button>
              <button
                className="icon-button secondary"
                type="button"
                onClick={() => setSearchOpen((open) => !open)}
                aria-pressed={searchOpen}
                aria-label="Search events"
              >
                <Search size={16} aria-hidden="true" />
              </button>
              <Link
                className="icon-button secondary"
                href="/calendar/calendars"
                aria-label="Manage event categories"
                title="Event categories"
              >
                <Layers size={16} aria-hidden="true" />
              </Link>
              <button className="calendar-add-desktop" type="button" onClick={() => setEditorDay(focusDate)}>
                <Plus size={16} aria-hidden="true" />
                Add
              </button>
            </div>
          </div>

          <div className="calendar-selectors-row">
            <label className="calendar-selector">
              {/* The household member to view the calendar as — filters by the
                  canonical event-membership relationship (member_ids, backed by
                  CalendarEventMember), not by a CalendarEventLabel category.
                  "Everyone" (value "") applies no member filter. */}
              <span className="sr-only">Filter by household member</span>
              <select value={memberFilter} onChange={(event) => chooseMember(event.target.value)} aria-label="Filter by household member">
                <option value="">Everyone</option>
                {members.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.display_name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
            <label className="calendar-selector calendar-view-selector">
              <span className="sr-only">Calendar view</span>
              <select
                value={view}
                onChange={(event) => chooseView(event.target.value as ViewMode)}
                aria-label="Calendar view"
              >
                <option value="month">Month</option>
                <option value="week">Week</option>
                <option value="day">Day</option>
                <option value="agenda">Schedule</option>
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
          </div>

          {birthdaysInRange.length > 0 && (
            <p className="notice calendar-birthday-banner">
              🎂{" "}
              {birthdaysInRange
                .map(
                  (entry) =>
                    `${entry.display_name}'s birthday (${new Date(
                      entry.next_occurrence_date,
                    ).toLocaleDateString("en-GB", { day: "numeric", month: "short" })})`,
                )
                .join(" · ")}
            </p>
          )}

          {searchOpen && (
            <>
              <div className="calendar-search">
                <Search size={16} aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Search events"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  autoFocus
                  aria-label="Search events by title"
                />
                {query && (
                  <button
                    type="button"
                    className="icon-button secondary"
                    onClick={() => setQuery("")}
                    aria-label="Clear search"
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
              <div className="calendar-selectors-row">
                <label className="calendar-selector">
                  {/* This filters by CalendarEventLabel — a free-form, unlimited event
                      tag (Family/School/Work/...), not the commercial "event category"
                      (HomeCalendar) concept limited by calendar.max_categories, and not
                      the household-member filter above even when a label happens to
                      share a member's name — see
                      docs/architecture/commercial-entitlements.md#commercial-plan-cleanup. */}
                  <span className="sr-only">Filter by category</span>
                  <select value={labelFilter} onChange={(event) => chooseLabel(event.target.value)} aria-label="Filter by category">
                    <option value="">{activeHome?.name ?? "Household"} calendar</option>
                    {labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}
                  </select>
                  <ChevronDown size={14} aria-hidden="true" />
                </label>
              </div>
            </>
          )}
        </header>

        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {view === "month" && (
          <MonthView
            cells={cells}
            events={visibleEvents}
            focusDate={focusDate}
            timeZone={calendarTimezone}
            onDay={openDay}
            onEvent={setSelectedEvent}
          />
        )}

        {view === "week" && (
          <section className="week-grid" aria-label="Week view">
            {Array.from({ length: 7 }, (_, index) => {
              const day = new Date(range.start);
              day.setUTCDate(day.getUTCDate() + index);
              const dayEvents = eventsForDay(visibleEvents, day, calendarTimezone);
              return (
                <article
                  className={
                    dateKey(day) === zonedDateKey(new Date(), calendarTimezone)
                      ? "today"
                      : ""
                  }
                  key={dateKey(day)}
                >
                  <button
                    className="week-day-heading"
                    type="button"
                    onClick={() => openDay(day)}
                  >
                    <span>{displayDate(day, { weekday: "short" }, "UTC")}</span>
                    <strong>{day.getUTCDate()}</strong>
                  </button>
                  <EventList
                    events={dayEvents}
                    members={members}
                    memberNames={memberNames}
                    timeZone={calendarTimezone}
                    onSelect={setSelectedEvent}
                    compact
                  />
                </article>
              );
            })}
          </section>
        )}

        {view === "day" && (
          <section className="day-view card" aria-label="Day view">
            <EventList
              events={focusedEvents}
              members={members}
              memberNames={memberNames}
              timeZone={calendarTimezone}
                    onSelect={setSelectedEvent}
            />
          </section>
        )}

        {view === "agenda" && (
          <section className="agenda-view" aria-label="Upcoming events">
            {visibleEvents.length === 0 ? (
              <p className="card hint">{scheduleEmptyMessage}</p>
            ) : (
              Array.from(byDay.entries())
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, rows]) => (
                  <article className="agenda-day" key={key}>
                    <h2>{relativeDayHeading(key, calendarTimezone)}</h2>
                    <EventList
                      events={rows}
                      members={members}
                      memberNames={memberNames}
                      timeZone={calendarTimezone}
                    onSelect={setSelectedEvent}
                    />
                  </article>
                ))
            )}
          </section>
        )}

        <button
          className="calendar-fab"
          type="button"
          onClick={() => setEditorDay(focusDate)}
          aria-label="Add calendar event"
        >
          +
        </button>

        {selectedDay && (
          <BottomSheet
            title={displayDate(
              selectedDay,
              { weekday: "long", day: "numeric", month: "long" },
              "UTC",
            )}
            onDismiss={() => setSelectedDay(null)}
          >
            <EventList
              events={eventsForDay(visibleEvents, selectedDay, calendarTimezone)}
              members={members}
              memberNames={memberNames}
              timeZone={calendarTimezone}
                    onSelect={(event) => {
                setSelectedDay(null);
                setSelectedEvent(event);
              }}
            />
            <button
              className="sheet-primary"
              type="button"
              onClick={() => {
                setEditorDay(selectedDay);
                setSelectedDay(null);
              }}
            >
              Add event on this day
            </button>
          </BottomSheet>
        )}

        {editorDay && (
          <BottomSheet
            title="Add event"
            onDismiss={() => setEditorDay(null)}
            fullHeight
          >
            <EventForm
              labels={labels}
              members={members}
              initialDay={editorDay}
              timeZone={calendarTimezone}
              busy={busy}
              submitLabel="Save event"
              sharedEventsEnabled={sharedEventsEnabled}
              onSubmit={create}
              onCancel={() => setEditorDay(null)}
            />
          </BottomSheet>
        )}

        {selectedEvent && (
          <BottomSheet
            title="Event details"
            onDismiss={() => setSelectedEvent(null)}
            fullHeight
          >
            <EventForm
              labels={labels}
              members={members}
              initial={selectedEvent}
              initialDay={new Date(selectedEvent.start_at)}
              timeZone={calendarTimezone}
              busy={busy}
              submitLabel="Save changes"
              sharedEventsEnabled={sharedEventsEnabled}
              onSubmit={update}
              onCancel={() => setSelectedEvent(null)}
              onDelete={remove}
            />
          </BottomSheet>
        )}
      </main>
    </AppShell>
  );
}

// Show at most this many event bars per week before collapsing the rest into a
// "+N more" indicator — a week with nothing more than this stays compact instead of
// reserving space for events it doesn't have.
const MONTH_VISIBLE_ROW_CAP = 3;

function MonthView({
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
                    style={{ "--event-color": resolveColour(event.label?.color ?? "teal"), gridColumn: `${start + 1} / ${end + 2}`, gridRow: row + 2 } as React.CSSProperties}
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

function EventList({
  events,
  members,
  memberNames,
  timeZone,
  onSelect,
  compact = false,
}: {
  events: EventOccurrence[];
  members: Member[];
  memberNames: Map<string, string>;
  timeZone: string;
  onSelect: (event: EventOccurrence) => void;
  compact?: boolean;
}) {
  if (!events.length) return <p className="hint">No events</p>;
  return (
    <div className={`event-list${compact ? " compact" : ""}`}>
      {events.map((event) => {
        const people = event.member_ids
          .map((id) => memberNames.get(id))
          .filter(Boolean);
        const firstMember = members.find((member) =>
          event.member_ids.includes(member.user_id),
        );
        return (
          <button
            className="event-row"
            type="button"
            key={event.occurrence_id}
            onClick={() => onSelect(event)}
          >
            <span
              className="event-colour"
              style={{ background: resolveColour(event.label?.color ?? "teal") }}
              aria-label={event.label?.name ?? "Family event"}
            />
            <span className="event-time">{eventTime(event, timeZone)}</span>
            <span className="event-copy">
              <strong>{event.title}</strong>
              <small>
                {[people.join(", "), event.label?.name, event.location_text, event.reminder_minutes !== null ? "Reminder set" : ""]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </span>
            {firstMember && (
              <Avatar
                id={firstMember.user_id}
                name={firstMember.display_name}
                colour={firstMember.colour}
                avatarVersion={firstMember.avatar_version}
                size="sm"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
