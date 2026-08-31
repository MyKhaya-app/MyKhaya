"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { Member, Reminder, ReminderCadence, ReminderRepeat, RoutineScope } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";

const REPEAT_LABELS: Record<ReminderRepeat, string> = {
  never: "Never",
  daily: "Daily",
  weekly: "Weekly",
};

const CADENCE_LABELS: Record<ReminderCadence, string> = {
  once: "Once",
  hourly: "Hourly until completed",
  daily: "Daily until completed",
  weekly: "Weekly until completed",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

type Section = "overdue" | "today" | "upcoming" | "completed";

function sectionFor(reminder: Reminder, today: string): Section | null {
  if (reminder.completed_today) return "completed";
  if (!reminder.next_occurrence_date) return null;
  if (reminder.next_occurrence_date < today) return "overdue";
  if (reminder.next_occurrence_date === today) return "today";
  return "upcoming";
}

export default function ReminderSettings() {
  const { activeHome, activeHomeId } = useActiveHome();
  const canManage = activeHome?.capabilities.includes("household.manage_reminders") ?? false;
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [tab, setTab] = useState<RoutineScope>("personal");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Reminder | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!activeHomeId) return;
    const response = await api.reminders(activeHomeId);
    setReminders(response.items);
  }, [activeHomeId]);

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  useEffect(() => {
    if (activeHomeId) api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId]);

  function openForm(reminder: Reminder | null) {
    setEditing(reminder);
    setShowForm(true);
    setError("");
  }

  async function toggleComplete(reminder: Reminder) {
    if (!activeHomeId || !reminder.next_occurrence_date) return;
    const previous = reminders;
    // Optimistic: reflect completion immediately, restore + surface an error if the
    // request fails — same rollback convention as Home's routine completion.
    setReminders((value) =>
      value.map((item) =>
        item.id === reminder.id
          ? { ...item, completed_today: !reminder.completed_today }
          : item,
      ),
    );
    setError("");
    try {
      if (reminder.completed_today) {
        await api.uncompleteReminder(activeHomeId, reminder.id, reminder.next_occurrence_date);
      } else {
        await api.completeReminder(activeHomeId, reminder.id, reminder.next_occurrence_date);
      }
      await load();
    } catch (cause) {
      setReminders(previous);
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
    const scope = (form.get("scope") as RoutineScope | null) ?? "personal";
    const assignee = (form.get("assignee") as string) || "";
    const payload = {
      title: ((form.get("title") as string | null) ?? "").trim(),
      description: (form.get("description") as string) || null,
      scope,
      due_date: (form.get("due_date") as string | null) ?? todayIso(),
      due_time: ((form.get("due_time") as string | null) || "09:00") + ":00",
      repeat: (form.get("repeat") as ReminderRepeat | null) ?? "never",
      cadence: (form.get("cadence") as ReminderCadence | null) ?? "once",
      member_ids: scope === "household" && assignee ? [assignee] : [],
    };
    try {
      if (editing) {
        await api.updateReminder(activeHomeId, editing.id, {
          ...payload,
          enabled: editing.enabled,
          expected_updated_at: editing.updated_at,
        });
        setMessage("Reminder updated.");
      } else {
        await api.createReminder(activeHomeId, payload);
        setMessage("Reminder created.");
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

  async function remove(reminder: Reminder) {
    if (!activeHomeId) return;
    if (!window.confirm(`Delete "${reminder.title}"? This cannot be undone.`)) return;
    setError("");
    try {
      await api.deleteReminder(activeHomeId, reminder.id);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  const today = todayIso();
  const filtered = useMemo(
    () => reminders.filter((reminder) => reminder.scope === tab),
    [reminders, tab],
  );
  const sections = useMemo(() => {
    const groups: Record<Section, Reminder[]> = {
      overdue: [],
      today: [],
      upcoming: [],
      completed: [],
    };
    for (const reminder of filtered) {
      const section = sectionFor(reminder, today);
      if (section) groups[section].push(reminder);
    }
    return groups;
  }, [filtered, today]);

  function renderReminder(reminder: Reminder) {
    const assignedMember = members.find((member) =>
      reminder.member_ids.includes(member.user_id),
    );
    return (
      <div className="card details" key={reminder.id}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ minWidth: 0 }}>
            <label className="check-row" style={{ display: "flex", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={reminder.completed_today}
                disabled={!reminder.next_occurrence_date}
                onChange={() => toggleComplete(reminder)}
              />
              <span>
                <strong style={reminder.completed_today ? { textDecoration: "line-through" } : undefined}>
                  {reminder.title}
                </strong>
                {reminder.description && <p>{reminder.description}</p>}
                <small>
                  {reminder.next_occurrence_date ?? "No upcoming date"} · {reminder.due_time.slice(0, 5)} ·{" "}
                  {REPEAT_LABELS[reminder.repeat]} · {CADENCE_LABELS[reminder.cadence]}
                  {reminder.scope === "household" && (
                    <> · {assignedMember ? assignedMember.display_name : "Household"}</>
                  )}
                  {!reminder.enabled ? " · Disabled" : ""}
                </small>
              </span>
            </label>
          </div>
          {canManage && (
            <div style={{ display: "flex", gap: "0.5rem", flexShrink: 0 }}>
              <button type="button" className="secondary" onClick={() => openForm(reminder)}>
                Edit
              </button>
              <button type="button" className="secondary" onClick={() => remove(reminder)}>
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <SettingsPage title="Reminders">
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

      <div className="routine-choice" role="group" aria-label="Personal or household reminders">
        {(["personal", "household"] as RoutineScope[]).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={tab === value}
            className={tab === value ? "toggle-active" : "secondary"}
            onClick={() => setTab(value)}
          >
            {value === "personal" ? "Personal" : "Household"}
          </button>
        ))}
      </div>

      {(["overdue", "today", "upcoming", "completed"] as Section[]).map((section) =>
        sections[section].length > 0 ? (
          <section key={section}>
            <h2>
              {section === "overdue" && "Overdue"}
              {section === "today" && "Today"}
              {section === "upcoming" && "Upcoming"}
              {section === "completed" && "Completed"}
            </h2>
            <div className="settings-list">{sections[section].map(renderReminder)}</div>
          </section>
        ) : null,
      )}
      {filtered.length === 0 && <p>No {tab} reminders yet.</p>}

      {canManage && !showForm && (
        <button type="button" onClick={() => openForm(null)}>
          Add a reminder
        </button>
      )}

      {canManage && showForm && (
        <form className="card details routine-form" key={editing?.id ?? "new"} onSubmit={save}>
          <h2>{editing ? "Edit reminder" : "New reminder"}</h2>
          <fieldset>
            <legend>Reminder</legend>
            <label>
              Title
              <input name="title" required maxLength={160} defaultValue={editing?.title ?? ""} />
            </label>
            <label>
              Notes (optional)
              <input name="description" maxLength={1000} defaultValue={editing?.description ?? ""} />
            </label>
          </fieldset>
          <fieldset>
            <legend>Who</legend>
            <label>
              Scope
              <select name="scope" defaultValue={editing?.scope ?? tab}>
                <option value="personal">Personal — only reminds you</option>
                <option value="household">Household — reminds the home</option>
              </select>
            </label>
            <label>
              Assign to (household only)
              <select
                name="assignee"
                defaultValue={
                  editing?.member_ids[0] ?? ""
                }
              >
                <option value="">Household / everyone</option>
                {members.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.display_name}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>
          <fieldset>
            <legend>When</legend>
            <div className="routine-date-grid">
              <label>
                Due date
                <input type="date" name="due_date" required defaultValue={editing?.due_date ?? today} />
              </label>
              <label>
                Due time
                <input
                  type="time"
                  name="due_time"
                  required
                  defaultValue={editing?.due_time.slice(0, 5) ?? "09:00"}
                />
              </label>
            </div>
            <label>
              Repeat
              <select name="repeat" defaultValue={editing?.repeat ?? "never"}>
                <option value="never">Never</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
              </select>
            </label>
            <label>
              Remind
              <select name="cadence" defaultValue={editing?.cadence ?? "once"}>
                <option value="once">Once</option>
                <option value="hourly">Hourly until completed</option>
                <option value="daily">Daily until completed</option>
                <option value="weekly">Weekly until completed</option>
              </select>
            </label>
          </fieldset>
          <div className="routine-form-actions">
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
