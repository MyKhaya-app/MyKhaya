"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, ChevronLeft, ChevronRight, Plus, Search, X } from "lucide-react";
import type {
  BirthdayEntry,
  EventLabel,
  EventOccurrence,
  EventPayload,
  Member,
  RecurrencePattern,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { useActiveHome } from "@/components/use-active-home";
import {
  agendaRange,
  dateKey,
  dayRange,
  eventsForDay,
  groupEventsByDay,
  monthCells,
  monthRange,
  weekRange,
} from "./calendar-utils";

type ViewMode = "month" | "week" | "day" | "agenda";
const VIEW_STORAGE = "mykhaya.calendar.view";
const LABEL_STORAGE = "mykhaya.calendar.label";

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function displayDate(
  value: Date | string,
  options: Intl.DateTimeFormatOptions,
) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    ...options,
  }).format(typeof value === "string" ? new Date(value) : value);
}

function eventTime(event: EventOccurrence) {
  if (event.is_all_day) return "All day";
  return displayDate(event.start_at, { hour: "2-digit", minute: "2-digit" });
}

function relativeDayHeading(key: string) {
  const today = dateKey(new Date());
  const tomorrow = new Date();
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  if (key === today) return "Today";
  if (key === dateKey(tomorrow)) return "Tomorrow";
  return displayDate(`${key}T00:00:00Z`, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function localInput(value: string | Date) {
  return (typeof value === "string" ? new Date(value) : value)
    .toISOString()
    .slice(0, 16);
}

function EventForm({
  labels,
  members,
  initial,
  initialDay,
  busy,
  submitLabel,
  onSubmit,
  onCancel,
  onDelete,
}: {
  labels: EventLabel[];
  members: Member[];
  initial?: EventOccurrence;
  initialDay: Date;
  busy: boolean;
  submitLabel: string;
  onSubmit: (payload: EventPayload) => Promise<void>;
  onCancel: () => void;
  onDelete?: () => Promise<void>;
}) {
  const startDefault = initial
    ? localInput(initial.start_at)
    : localInput(
        new Date(
          Date.UTC(
            initialDay.getUTCFullYear(),
            initialDay.getUTCMonth(),
            initialDay.getUTCDate(),
            9,
          ),
        ),
      );
  const endDefault = initial
    ? localInput(initial.end_at)
    : localInput(
        new Date(
          Date.UTC(
            initialDay.getUTCFullYear(),
            initialDay.getUTCMonth(),
            initialDay.getUTCDate(),
            10,
          ),
        ),
      );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const title = formText(data, "title").trim();
    const start = new Date(formText(data, "start"));
    const end = new Date(formText(data, "end"));
    await onSubmit({
      title,
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      timezone: initial?.timezone ?? "Europe/London",
      is_all_day: data.get("allDay") === "on",
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
      <label>
        Starts
        <input
          name="start"
          type="datetime-local"
          defaultValue={startDefault}
          required
        />
      </label>
      <label>
        Ends
        <input
          name="end"
          type="datetime-local"
          defaultValue={endDefault}
          required
        />
      </label>
      <label className="check-row form-wide">
        <input
          name="allDay"
          type="checkbox"
          defaultChecked={initial?.is_all_day}
        />
        All-day event
      </label>
      {members.length > 0 && (
        <fieldset className="form-wide">
          <legend>Household members</legend>
          <div className="member-checks">
            {members.map((member) => (
              <label className="check-row" key={member.user_id}>
                <input
                  name="members"
                  type="checkbox"
                  value={member.user_id}
                  defaultChecked={initial?.member_ids.includes(member.user_id)}
                />
                {member.display_name}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <label>
        Calendar or category
        <select name="label" defaultValue={initial?.label?.id ?? ""}>
          <option value="">Family calendar</option>
          {labels.map((label) => (
            <option key={label.id} value={label.id}>
              {label.name}
            </option>
          ))}
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
  const [focusDate, setFocusDate] = useState(new Date());
  const [events, setEvents] = useState<EventOccurrence[]>([]);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
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

  useEffect(() => {
    setLabelFilter(window.localStorage.getItem(LABEL_STORAGE) ?? "");
  }, []);

  function chooseLabel(next: string) {
    setLabelFilter(next);
    window.localStorage.setItem(LABEL_STORAGE, next);
  }

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

  const load = useCallback(async () => {
    if (!activeHomeId || !featureEnabled) return;
    const [labelRows, eventRows, memberRows] = await Promise.all([
      api.listLabels(activeHomeId),
      api.listEvents(activeHomeId, {
        start_at: range.start.toISOString(),
        end_at: range.end.toISOString(),
        page_size: 300,
      }),
      api.members(activeHomeId).catch(() => []),
    ]);
    setLabels(labelRows);
    setEvents(eventRows.items);
    setMembers(memberRows);
    api
      .birthdays(activeHomeId)
      .then((response) => setBirthdays(response.items))
      .catch(() => setBirthdays([]));
  }, [activeHomeId, featureEnabled, range.end, range.start]);

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

  const visibleEvents = useMemo(() => {
    const filtered = labelFilter
      ? events.filter((event) => (event.label?.id ?? "") === labelFilter)
      : events;
    if (!query.trim()) return filtered;
    const needle = query.trim().toLowerCase();
    return filtered.filter((event) => event.title.toLowerCase().includes(needle));
  }, [events, labelFilter, query]);
  const byDay = useMemo(() => groupEventsByDay(visibleEvents), [visibleEvents]);
  const cells = useMemo(() => monthCells(focusDate), [focusDate]);
  const memberNames = useMemo(
    () =>
      new Map(members.map((member) => [member.user_id, member.display_name])),
    [members],
  );

  function move(direction: -1 | 1) {
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

  const focusedEvents = eventsForDay(visibleEvents, focusDate);
  const birthdaysInRange = birthdays.filter((entry) => {
    const occurrence = new Date(entry.next_occurrence_date);
    return occurrence >= range.start && occurrence < range.end;
  });

  return (
    <AppShell>
      <main className="standard-page calendar-page">
        <header className="calendar-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>Calendar</h1>
          </div>
          <div className="calendar-heading-actions">
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => setSearchOpen((open) => !open)}
              aria-pressed={searchOpen}
              aria-label="Search events"
            >
              <Search size={18} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => setEditorDay(focusDate)}>
              <Plus size={18} aria-hidden="true" />
              Add
            </button>
          </div>
        </header>

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
        )}

        <div className="calendar-toolbar" aria-label="Calendar controls">
          <div
            className="view-switcher"
            role="group"
            aria-label="Calendar view"
          >
            {(
              [
                { mode: "agenda", label: "Schedule" },
                { mode: "day", label: "Day" },
                { mode: "week", label: "Week" },
                { mode: "month", label: "Month" },
              ] as { mode: ViewMode; label: string }[]
            ).map(({ mode, label }) => (
              <button
                type="button"
                key={mode}
                className={view === mode ? "active" : "secondary"}
                aria-pressed={view === mode}
                onClick={() => chooseView(mode)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="date-navigation">
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(-1)}
              aria-label="Previous period"
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <button
              className="secondary today-button"
              type="button"
              onClick={() => setFocusDate(new Date())}
            >
              Today
            </button>
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(1)}
              aria-label="Next period"
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="calendar-filter-row">
          <label className="calendar-selector">
            <span className="sr-only">Calendar or category</span>
            <select value={labelFilter} onChange={(event) => chooseLabel(event.target.value)} aria-label="Calendar or category">
              <option value="">{activeHome?.name ?? "Household"} calendar</option>
              {labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}
            </select>
            <ChevronDown size={16} aria-hidden="true" />
          </label>
        </div>

        <h2 className="calendar-period">
          {view === "day"
            ? displayDate(focusDate, {
                weekday: "long",
                day: "numeric",
                month: "long",
                year: "numeric",
              })
            : displayDate(focusDate, { month: "long", year: "numeric" })}
        </h2>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {view === "month" && (
          <MonthView cells={cells} events={visibleEvents} focusDate={focusDate} onDay={openDay} onEvent={setSelectedEvent} />
        )}

        {view === "week" && (
          <section className="week-grid" aria-label="Week view">
            {Array.from({ length: 7 }, (_, index) => {
              const day = new Date(range.start);
              day.setUTCDate(day.getUTCDate() + index);
              const dayEvents = eventsForDay(visibleEvents, day);
              return (
                <article
                  className={
                    dateKey(day) === dateKey(new Date()) ? "today" : ""
                  }
                  key={dateKey(day)}
                >
                  <button
                    className="week-day-heading"
                    type="button"
                    onClick={() => openDay(day)}
                  >
                    <span>{displayDate(day, { weekday: "short" })}</span>
                    <strong>{day.getUTCDate()}</strong>
                  </button>
                  <EventList
                    events={dayEvents}
                    members={members}
                    memberNames={memberNames}
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
              onSelect={setSelectedEvent}
            />
          </section>
        )}

        {view === "agenda" && (
          <section className="agenda-view" aria-label="Upcoming events">
            {events.length === 0 ? (
              <p className="card hint">No upcoming events.</p>
            ) : (
              Array.from(byDay.entries())
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, rows]) => (
                  <article className="agenda-day" key={key}>
                    <h2>{relativeDayHeading(key)}</h2>
                    <EventList
                      events={rows}
                      members={members}
                      memberNames={memberNames}
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
            title={displayDate(selectedDay, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
            onDismiss={() => setSelectedDay(null)}
          >
            <EventList
              events={eventsForDay(visibleEvents, selectedDay)}
              members={members}
              memberNames={memberNames}
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
              busy={busy}
              submitLabel="Save event"
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
              busy={busy}
              submitLabel="Save changes"
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

function eventEndKey(event: EventOccurrence) {
  const end = new Date(event.end_at);
  if (event.is_all_day && event.end_at.includes("T00:00:00")) end.setUTCDate(end.getUTCDate() - 1);
  return dateKey(end);
}

function MonthView({
  cells,
  events,
  focusDate,
  onDay,
  onEvent,
}: {
  cells: Date[];
  events: EventOccurrence[];
  focusDate: Date;
  onDay: (day: Date) => void;
  onEvent: (event: EventOccurrence) => void;
}) {
  const todayKey = dateKey(new Date());
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
            .filter((event) => eventEndKey(event) >= weekStart && dateKey(event.start_at) <= weekEnd)
            .sort((a, b) => dateKey(a.start_at).localeCompare(dateKey(b.start_at)) || a.title.localeCompare(b.title))
            .forEach((event) => {
              const start = Math.max(0, days.findIndex((day) => dateKey(day) >= dateKey(event.start_at)));
              const end = Math.min(6, days.reduce((last, day, index) => dateKey(day) <= eventEndKey(event) ? index : last, -1));
              if (end < start) return;
              let row = rowIntervals.findIndex((intervals) => intervals.every((interval) => end < interval.start || start > interval.end));
              if (row === -1) row = rowIntervals.length;
              (rowIntervals[row] ??= []).push({ start, end });
              rows.push({ event, start, end, row });
            });
          const hiddenByDay = days.map((day) => rows.filter((item) => item.row >= 4 && item.start <= days.indexOf(day) && item.end >= days.indexOf(day)).length);
          return (
            <div className="calendar-week" key={weekStart}>
              {days.map((day, index) => {
                const key = dateKey(day);
                const count = events.filter((event) => dateKey(event.start_at) <= key && eventEndKey(event) >= key).length;
                const hidden = hiddenByDay[index] ?? 0;
                return (
                  <article className={`calendar-day${key === todayKey ? " today" : ""}${day.getUTCMonth() !== focusDate.getUTCMonth() ? " outside" : ""}`} key={key}>
                    <button className="day-number" type="button" onClick={() => onDay(day)} aria-label={`${displayDate(day, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}, ${count} events`}>
                      <span>{day.getUTCDate()}</span>
                    </button>
                    {hidden > 0 && <button className="overflow-events" type="button" onClick={() => onDay(day)}>+{hidden} more</button>}
                  </article>
                );
              })}
              {rows.filter((item) => item.row < 4).map(({ event, start, end, row }) => (
                <button
                  key={`${event.occurrence_id}-${weekStart}`}
                  type="button"
                  className="month-event"
                  style={{ "--event-color": event.label?.color ?? "#456b76", gridColumn: `${start + 1} / ${end + 2}`, gridRow: row + 2 } as React.CSSProperties}
                  onClick={() => onEvent(event)}
                  aria-label={`${eventTime(event)} ${event.title}`}
                  title={event.title}
                >
                  <span aria-hidden="true" />
                  <b>{event.is_all_day ? "" : eventTime(event)}</b>{dateKey(event.start_at) < weekStart ? "↳ " : ""}{event.title}
                </button>
              ))}
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
  onSelect,
  compact = false,
}: {
  events: EventOccurrence[];
  members: Member[];
  memberNames: Map<string, string>;
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
              style={{ background: event.label?.color ?? "#456b76" }}
              aria-label={event.label?.name ?? "Family event"}
            />
            <span className="event-time">{eventTime(event)}</span>
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
