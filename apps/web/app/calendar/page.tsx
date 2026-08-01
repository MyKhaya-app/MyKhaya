"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { EventLabel, EventOccurrence, RecurrencePattern } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { useActiveHome } from "@/components/use-active-home";

type ViewMode = "month" | "week" | "agenda";

function isoDate(value: Date) {
  return value.toISOString();
}

function dateLabel(value: string, timezone: string) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

function monthRange(base: Date) {
  const start = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1));
  const end = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 1));
  return { start, end };
}

function weekRange(base: Date) {
  const day = (base.getUTCDay() + 6) % 7;
  const start = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate() - day));
  const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + 7));
  return { start, end };
}

function agendaRange(base: Date) {
  const start = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate() - 14));
  const end = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate() + 45));
  return { start, end };
}

function dayKey(value: string) {
  return value.slice(0, 10);
}

function formString(form: FormData, key: string, fallback = "") {
  const value = form.get(key);
  return typeof value === "string" ? value : fallback;
}

export default function CalendarPage() {
  const router = useRouter();
  const { activeHome, activeHomeId } = useActiveHome();
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [featureChecked, setFeatureChecked] = useState(false);
  const [view, setView] = useState<ViewMode>("month");
  const [focusDate, setFocusDate] = useState<Date>(new Date());
  const [events, setEvents] = useState<EventOccurrence[]>([]);
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [selected, setSelected] = useState<EventOccurrence | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const range = useMemo(() => {
    if (view === "month") return monthRange(focusDate);
    if (view === "week") return weekRange(focusDate);
    return agendaRange(focusDate);
  }, [focusDate, view]);

  const eventsByDay = useMemo(() => {
    const output = new Map<string, EventOccurrence[]>();
    for (const event of events) {
      const key = dayKey(event.start_at);
      const current = output.get(key) ?? [];
      current.push(event);
      output.set(key, current);
    }
    return output;
  }, [events]);

  async function reload() {
    if (!activeHomeId || !featureEnabled) return;
    const [labelRows, eventRows] = await Promise.all([
      api.listLabels(activeHomeId),
      api.listEvents(activeHomeId, {
        start_at: isoDate(range.start),
        end_at: isoDate(range.end),
        page_size: 300,
      }),
    ]);
    setLabels(labelRows);
    setEvents(eventRows.items);
  }

  useEffect(() => {
    if (!activeHomeId) {
      setFeatureEnabled(false);
      setFeatureChecked(false);
      return;
    }
    setFeatureChecked(false);
    api
      .featureMatrix(activeHomeId)
      .then((matrix) => {
        const enabled =
          matrix.features.find((item) => item.feature === "calendar")?.enabled === true;
        setFeatureEnabled(enabled);
        setFeatureChecked(true);
        if (!enabled) router.replace("/home");
      })
      .catch(() => {
        setFeatureEnabled(false);
        setFeatureChecked(true);
        router.replace("/home");
      });
  }, [activeHomeId, router]);

  useEffect(() => {
    if (!activeHomeId || !featureEnabled) return;
    setError("");
    reload().catch((reason: Error) => setError(reason.message));
  }, [activeHomeId, featureEnabled, range.start.toISOString(), range.end.toISOString()]);

  async function createEvent(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!activeHomeId) return;
    setBusy(true);
    setError("");
    const form = new FormData(e.currentTarget);
    const start = new Date(formString(form, "start"));
    const end = new Date(formString(form, "end"));
    const recurrence = formString(form, "recurrence", "none") as RecurrencePattern;
    const title = formString(form, "title").trim();
    const description = formString(form, "description");
    const location = formString(form, "location");
    const labelId = formString(form, "label");
    const validLabelIds = new Set(labels.map((label) => label.id));
    const safeLabelId = labelId && validLabelIds.has(labelId) ? labelId : null;
    const reminderRaw = formString(form, "reminder");

    try {
      await api.createEvent(activeHomeId, {
        title,
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        timezone: "Europe/London",
        is_all_day: form.get("allDay") === "on",
        description: description || null,
        location_text: location || null,
        label_id: safeLabelId,
        reminder_minutes: reminderRaw ? Number(reminderRaw) : null,
        recurrence,
        recurrence_interval: 1,
      });
      (e.currentTarget as HTMLFormElement).reset();
      await reload();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "We could not save your event.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function deleteEvent() {
    if (!activeHomeId || !selected) return;
    if (!window.confirm("Delete event?")) return;
    try {
      await api.deleteEvent(activeHomeId, selected.event_id);
      setSelected(null);
      await reload();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "Could not delete event.",
      );
    }
  }

  async function saveSelected(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!activeHomeId || !selected) return;
    const form = new FormData(e.currentTarget);
    const start = new Date(formString(form, "start"));
    const end = new Date(formString(form, "end"));
    const title = formString(form, "title").trim();
    const description = formString(form, "description");
    const location = formString(form, "location");
    const labelId = formString(form, "label");
    const validLabelIds = new Set(labels.map((label) => label.id));
    const safeLabelId = labelId && validLabelIds.has(labelId) ? labelId : null;
    const reminderRaw = formString(form, "reminder");
    const recurrence = formString(form, "recurrence", "none") as RecurrencePattern;
    try {
      const updated = await api.updateEvent(activeHomeId, selected.event_id, {
        title,
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        timezone: selected.timezone,
        is_all_day: form.get("allDay") === "on",
        description: description || null,
        location_text: location || null,
        label_id: safeLabelId,
        member_ids: selected.member_ids,
        reminder_minutes: reminderRaw ? Number(reminderRaw) : null,
        recurrence,
        recurrence_interval: 1,
        recurrence_until: null,
        recurrence_count: null,
        expected_updated_at: selected.updated_at,
      });
      setSelected(updated);
      await reload();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "This event changed. Reload and try again.",
      );
    }
  }

  const monthCells = useMemo(() => {
    const current = monthRange(focusDate);
    const start = new Date(current.start);
    const shift = (start.getUTCDay() + 6) % 7;
    start.setUTCDate(start.getUTCDate() - shift);
    return Array.from({ length: 42 }, (_, index) => {
      const day = new Date(start);
      day.setUTCDate(start.getUTCDate() + index);
      return day;
    });
  }, [focusDate]);

  if (!featureChecked || !featureEnabled) {
    return (
      <AppShell>
        <main className="standard-page"><p role="status">Checking feature availability…</p></main>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>Calendar</h1>
            <p>Shared events for your Home.</p>
          </div>
          <div className="calendar-actions">
            <button className={view === "month" ? "" : "secondary"} onClick={() => setView("month")} type="button">Month</button>
            <button className={view === "week" ? "" : "secondary"} onClick={() => setView("week")} type="button">Week</button>
            <button className={view === "agenda" ? "" : "secondary"} onClick={() => setView("agenda")} type="button">Agenda</button>
            <button className="secondary" onClick={() => setFocusDate(new Date())} type="button">Today</button>
          </div>
        </div>

        <div className="calendar-nav">
          <button type="button" onClick={() => setFocusDate(new Date(focusDate.getTime() - 86400000 * (view === "week" ? 7 : 30)))}>
            Previous
          </button>
          <strong>
            {new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(focusDate)}
          </strong>
          <button type="button" onClick={() => setFocusDate(new Date(focusDate.getTime() + 86400000 * (view === "week" ? 7 : 30)))}>
            Next
          </button>
        </div>

        {error && <p className="notice error">{error}</p>}

        <section className="card calendar-panel">
          {view === "month" && (
            <>
              <div className="calendar-weekdays">
                {"Mon Tue Wed Thu Fri Sat Sun".split(" ").map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
              <div className="calendar-grid">
                {monthCells.map((day) => {
                  const key = day.toISOString().slice(0, 10);
                  const dayEvents = eventsByDay.get(key) ?? [];
                  const isToday = key === new Date().toISOString().slice(0, 10);
                  return (
                    <article key={key} className={isToday ? "calendar-day today" : "calendar-day"}>
                      <header>{day.getUTCDate()}</header>
                      <div>
                        {dayEvents.slice(0, 3).map((event) => (
                          <button key={event.occurrence_id} type="button" className="calendar-event" onClick={() => setSelected(event)}>
                            {event.is_all_day ? "All day" : new Date(event.start_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} {event.title}
                          </button>
                        ))}
                        {dayEvents.length > 3 && <small>+{dayEvents.length - 3} more</small>}
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          )}

          {view === "week" && (
            <div className="agenda-list">
              {Array.from({ length: 7 }, (_, index) => {
                const day = new Date(range.start);
                day.setUTCDate(day.getUTCDate() + index);
                const key = day.toISOString().slice(0, 10);
                const dayEvents = eventsByDay.get(key) ?? [];
                return (
                  <article key={key}>
                    <h2>{new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "2-digit", month: "short" }).format(day)}</h2>
                    {!dayEvents.length ? (
                      <p className="hint">No events</p>
                    ) : (
                      dayEvents.map((event) => (
                        <button key={event.occurrence_id} type="button" className="calendar-event" onClick={() => setSelected(event)}>
                          <strong>{event.title}</strong>
                          <small>{dateLabel(event.start_at, event.timezone)}</small>
                        </button>
                      ))
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {view === "agenda" && (
            <div className="agenda-list">
              {!events.length ? (
                <p className="hint">No events yet. Add your first family event to get started.</p>
              ) : (
                events.map((event) => (
                  <article key={event.occurrence_id}>
                    <button className="calendar-event" type="button" onClick={() => setSelected(event)}>
                      <strong>{event.title}</strong>
                      <small>{dateLabel(event.start_at, event.timezone)}</small>
                    </button>
                  </article>
                ))
              )}
            </div>
          )}
        </section>

        <section className="card details">
          <h2>Add event</h2>
          <form onSubmit={createEvent}>
            <label>
              Title
              <input name="title" required maxLength={180} />
            </label>
            <label>
              Start
              <input name="start" type="datetime-local" required />
            </label>
            <label>
              End
              <input name="end" type="datetime-local" required />
            </label>
            <label>
              All day
              <input name="allDay" type="checkbox" />
            </label>
            <label>
              Label
              <select name="label" defaultValue="">
                <option value="">None</option>
                {labels.map((label) => (
                  <option key={label.id} value={label.id}>{label.name}</option>
                ))}
              </select>
            </label>
            <label>
              Repeat
              <select name="recurrence" defaultValue="none">
                <option value="none">Does not repeat</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="yearly">Yearly</option>
                <option value="weekdays">Weekdays</option>
              </select>
            </label>
            <label>
              Reminder
              <select name="reminder" defaultValue="">
                <option value="">None</option>
                <option value="0">At time of event</option>
                <option value="5">5 minutes before</option>
                <option value="15">15 minutes before</option>
                <option value="30">30 minutes before</option>
                <option value="60">1 hour before</option>
                <option value="1440">1 day before</option>
              </select>
            </label>
            <label>
              Location
              <input name="location" maxLength={200} />
            </label>
            <label>
              Description
              <textarea name="description" maxLength={2000} />
            </label>
            <button disabled={busy}>{busy ? "Saving…" : "Save event"}</button>
          </form>
        </section>

        {selected && (
          <section className="card details">
            <h2>Event details</h2>
            <form onSubmit={saveSelected}>
              <label>
                Title
                <input name="title" defaultValue={selected.title} required maxLength={180} />
              </label>
              <label>
                Start
                <input name="start" type="datetime-local" defaultValue={new Date(selected.start_at).toISOString().slice(0, 16)} required />
              </label>
              <label>
                End
                <input name="end" type="datetime-local" defaultValue={new Date(selected.end_at).toISOString().slice(0, 16)} required />
              </label>
              <label>
                All day
                <input name="allDay" type="checkbox" defaultChecked={selected.is_all_day} />
              </label>
              <label>
                Repeat
                <select name="recurrence" defaultValue={selected.recurrence}>
                  <option value="none">Does not repeat</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="yearly">Yearly</option>
                  <option value="weekdays">Weekdays</option>
                </select>
              </label>
              <label>
                Label
                <select name="label" defaultValue={selected.label?.id ?? ""}>
                  <option value="">None</option>
                  {labels.map((label) => (
                    <option key={label.id} value={label.id}>{label.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Reminder
                <select name="reminder" defaultValue={selected.reminder_minutes ?? ""}>
                  <option value="">None</option>
                  <option value="0">At time of event</option>
                  <option value="5">5 minutes before</option>
                  <option value="15">15 minutes before</option>
                  <option value="30">30 minutes before</option>
                  <option value="60">1 hour before</option>
                  <option value="1440">1 day before</option>
                </select>
              </label>
              <label>
                Location
                <input name="location" maxLength={200} defaultValue={selected.location_text ?? ""} />
              </label>
              <label>
                Description
                <textarea name="description" maxLength={2000} defaultValue={selected.description ?? ""} />
              </label>
              <div className="actions compact-actions">
                <button type="submit">Save changes</button>
                <button type="button" className="secondary" onClick={deleteEvent}>Delete event</button>
                <button type="button" className="secondary" onClick={() => setSelected(null)}>Close</button>
              </div>
            </form>
          </section>
        )}
      </main>
    </AppShell>
  );
}
