"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import type { Routine, RoutineReminderTiming, RoutineScope } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";

const TIMING_LABELS: Record<RoutineReminderTiming, string> = {
  evening_before: "The evening before",
  same_day: "The morning of",
  both: "Both",
};

const SCOPE_LABELS: Record<RoutineScope, string> = {
  personal: "Personal — only reminds you",
  household: "Household — reminds the home",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function RoutineSettings() {
  const { activeHome, activeHomeId } = useActiveHome();
  const canManage = activeHome?.capabilities.includes("household.manage_routines") ?? false;
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!activeHomeId) return;
    const response = await api.routines(activeHomeId);
    setRoutines(response.items);
  }, [activeHomeId]);

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  async function toggleComplete(routine: Routine) {
    if (!activeHomeId || !routine.next_occurrence_date) return;
    setError("");
    try {
      if (routine.completed_today) {
        await api.uncompleteRoutine(activeHomeId, routine.id, routine.next_occurrence_date);
      } else {
        await api.completeRoutine(activeHomeId, routine.id, routine.next_occurrence_date);
      }
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId) return;
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const payload = {
      title: ((form.get("title") as string | null) ?? "").trim(),
      description: (form.get("description") as string) || null,
      scope: (form.get("scope") as RoutineScope | null) ?? "household",
      interval_weeks: Number(form.get("interval_weeks") ?? 1),
      week_anchor_date: (form.get("week_anchor_date") as string | null) ?? todayIso(),
      reminder_timing: (form.get("reminder_timing") as RoutineReminderTiming) ?? "evening_before",
      is_critical: form.get("is_critical") === "on",
      pinned: form.get("pinned") === "on",
      start_date: (form.get("start_date") as string | null) ?? todayIso(),
      end_date: (form.get("end_date") as string) || null,
      member_ids: [],
    };
    try {
      if (editing) {
        await api.updateRoutine(activeHomeId, editing.id, {
          ...payload,
          enabled: editing.enabled,
          expected_updated_at: editing.updated_at,
        });
        setMessage("Routine updated.");
      } else {
        await api.createRoutine(activeHomeId, payload);
        setMessage("Routine created.");
      }
      setShowForm(false);
      setEditing(null);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(routine: Routine) {
    if (!activeHomeId) return;
    if (!window.confirm(`Delete "${routine.title}"? This cannot be undone.`)) return;
    setError("");
    try {
      await api.deleteRoutine(activeHomeId, routine.id);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <SettingsPage title="Routines">
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}

      <div className="settings-list">
        {routines.map((routine) => (
          <div className="card details" key={routine.id}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
              <div>
                <h2>{routine.title}</h2>
                {routine.description && <p>{routine.description}</p>}
                <small>
                  {routine.scope === "personal" ? "Personal" : "Household"} · Every{" "}
                  {routine.interval_weeks === 1 ? "week" : `${routine.interval_weeks} weeks`} ·{" "}
                  {TIMING_LABELS[routine.reminder_timing]}
                  {routine.is_critical ? " · Critical" : ""}
                  {!routine.enabled ? " · Disabled" : ""}
                </small>
                {routine.next_occurrence_date && (
                  <p>
                    Next: {routine.next_occurrence_date}
                    {routine.next_occurrence_date === todayIso() && (
                      <label className="check-row" style={{ display: "inline-flex", marginLeft: "0.75rem" }}>
                        <input
                          type="checkbox"
                          checked={routine.completed_today}
                          onChange={() => toggleComplete(routine)}
                        />{" "}
                        Done today
                      </label>
                    )}
                  </p>
                )}
              </div>
              {canManage && (
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setEditing(routine);
                      setShowForm(true);
                    }}
                  >
                    Edit
                  </button>
                  <button type="button" className="secondary" onClick={() => remove(routine)}>
                    Delete
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {routines.length === 0 && <p>No routines yet.</p>}
      </div>

      {canManage && !showForm && (
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          Add a routine
        </button>
      )}

      {canManage && showForm && (
        <form className="card details" onSubmit={save}>
          <h2>{editing ? "Edit routine" : "New routine"}</h2>
          <label>
            Title
            <input name="title" required maxLength={160} defaultValue={editing?.title ?? ""} />
          </label>
          <label>
            Description (optional)
            <input name="description" maxLength={1000} defaultValue={editing?.description ?? ""} />
          </label>
          <label>
            Who this is for
            <select name="scope" defaultValue={editing?.scope ?? "household"}>
              <option value="household">{SCOPE_LABELS.household}</option>
              <option value="personal">{SCOPE_LABELS.personal}</option>
            </select>
          </label>
          <label>
            Repeats every
            <select name="interval_weeks" defaultValue={String(editing?.interval_weeks ?? 1)}>
              <option value="1">Week</option>
              <option value="2">2 weeks (alternating)</option>
              <option value="3">3 weeks</option>
              <option value="4">4 weeks</option>
            </select>
          </label>
          <label>
            An occurrence date (used to anchor the schedule)
            <input
              type="date"
              name="week_anchor_date"
              required
              defaultValue={editing?.week_anchor_date ?? todayIso()}
            />
          </label>
          <label>
            Remind
            <select name="reminder_timing" defaultValue={editing?.reminder_timing ?? "evening_before"}>
              <option value="evening_before">The evening before</option>
              <option value="same_day">The morning of</option>
              <option value="both">Both</option>
            </select>
          </label>
          <label className="check-row">
            <input type="checkbox" name="is_critical" defaultChecked={editing?.is_critical ?? false} />{" "}
            Critical (e.g. medication — bypasses quiet hours)
          </label>
          <label className="check-row">
            <input type="checkbox" name="pinned" defaultChecked={editing?.pinned ?? false} />{" "}
            Pin to the Home screen checklist
          </label>
          <label>
            Starts
            <input type="date" name="start_date" required defaultValue={editing?.start_date ?? todayIso()} />
          </label>
          <label>
            Ends (optional)
            <input type="date" name="end_date" defaultValue={editing?.end_date ?? ""} />
          </label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setShowForm(false);
                setEditing(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </SettingsPage>
  );
}
