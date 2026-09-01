"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type {
  Member,
  Reminder,
  ReminderCadence,
  ReminderRepeat,
  Routine,
  RoutineReminderTiming,
  RoutineRepeatUnit,
  RoutineScope,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { FamilyUpsell } from "@/components/family-upsell";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { routineDueLabel } from "@/app/home/routine-utils";

// Routines and Reminders stay separate backend domains (separate models,
// APIs, completion semantics — see docs/architecture/notification-engine.md)
// but are presented as one "Routines & Reminders" module: users shouldn't
// have to know or care which API a given row happens to come from. Every
// action below still dispatches to the item's own source API rather than a
// generic one.

const TIMING_LABELS: Record<RoutineReminderTiming, string> = {
  evening_before: "The evening before",
  same_day: "The morning of",
  both: "Both",
};

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

const SCOPE_LABELS: Record<RoutineScope, string> = {
  personal: "Personal — only reminds you",
  household: "Household — reminds the home",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

type TypeFilter = "all" | "routines" | "reminders";
type Section = "overdue" | "today" | "upcoming" | "completed";

type UiItem =
  | { kind: "routine"; id: string; data: Routine }
  | { kind: "reminder"; id: string; data: Reminder };

function sectionFor(item: UiItem, today: string): Section | null {
  if (item.data.completed_today) return "completed";
  if (!item.data.next_occurrence_date) return null;
  if (item.data.next_occurrence_date < today) return "overdue";
  if (item.data.next_occurrence_date === today) return "today";
  return "upcoming";
}

function compareItems(a: UiItem, b: UiItem): number {
  const aDate = a.data.next_occurrence_date ?? "";
  const bDate = b.data.next_occurrence_date ?? "";
  if (aDate !== bDate) return aDate < bDate ? -1 : 1;
  const aTime = a.kind === "reminder" ? a.data.due_time : "";
  const bTime = b.kind === "reminder" ? b.data.due_time : "";
  if (aTime !== bTime) return aTime < bTime ? -1 : 1;
  return a.data.title.localeCompare(b.data.title);
}

function routineFrequencyLabel(routine: Routine): string {
  if (routine.repeat_unit === "daily") return "Daily";
  return `Every ${routine.interval_weeks === 1 ? "week" : `${routine.interval_weeks} weeks`}`;
}

function itemMetaLabel(item: UiItem): string {
  const scopeLabel = item.data.scope === "household" ? "Household" : "Personal";
  if (item.kind === "routine") {
    return `Routine · ${scopeLabel} · ${routineFrequencyLabel(item.data)}`;
  }
  const dueLabel = routineDueLabel(item.data.next_occurrence_date);
  const time = item.data.next_occurrence_date ? ` ${item.data.due_time.slice(0, 5)}` : "";
  return `Reminder · ${scopeLabel} · ${dueLabel}${time}`;
}

export default function RoutinesRemindersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { activeHome, activeHomeId } = useActiveHome();
  const canManageRoutines = activeHome?.capabilities.includes("household.manage_routines") ?? false;
  const canManageReminders = activeHome?.capabilities.includes("household.manage_reminders") ?? false;

  const initialType = searchParams?.get("type");
  const [typeTab, setTypeTab] = useState<TypeFilter>(
    initialType === "routines" || initialType === "reminders" ? initialType : "all",
  );
  const [scopeTab, setScopeTab] = useState<RoutineScope>("personal");

  const [routines, setRoutines] = useState<Routine[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [householdRoutinesEnabled, setHouseholdRoutinesEnabled] = useState(false);

  const [showCreateMenu, setShowCreateMenu] = useState(false);
  const [formKind, setFormKind] = useState<"routine" | "reminder" | null>(null);
  const [editingRoutine, setEditingRoutine] = useState<Routine | null>(null);
  const [editingReminder, setEditingReminder] = useState<Reminder | null>(null);
  const [repeatUnit, setRepeatUnit] = useState<RoutineRepeatUnit>("weekly");
  const [weekInterval, setWeekInterval] = useState(1);

  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const loadRoutines = useCallback(async () => {
    if (!activeHomeId) return;
    const response = await api.routines(activeHomeId);
    setRoutines(response.items);
  }, [activeHomeId]);

  const loadReminders = useCallback(async () => {
    if (!activeHomeId) return;
    const response = await api.reminders(activeHomeId);
    setReminders(response.items);
  }, [activeHomeId]);

  useEffect(() => {
    Promise.all([loadRoutines(), loadReminders()]).catch((cause: Error) => setError(cause.message));
  }, [loadRoutines, loadReminders]);

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => setHouseholdRoutinesEnabled(billing.household_routines_enabled))
      .catch(() => setHouseholdRoutinesEnabled(false));
  }, [activeHomeId]);

  useEffect(() => {
    if (activeHomeId) api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId]);

  function selectTypeTab(next: TypeFilter) {
    setTypeTab(next);
    const params = new URLSearchParams(searchParams?.toString());
    if (next === "all") params.delete("type");
    else params.set("type", next);
    const query = params.toString();
    router.replace(`/settings/routines-reminders${query ? `?${query}` : ""}`);
  }

  function closeForms() {
    setFormKind(null);
    setEditingRoutine(null);
    setEditingReminder(null);
    setShowCreateMenu(false);
  }

  function openNewRoutine() {
    setEditingRoutine(null);
    setEditingReminder(null);
    setRepeatUnit("weekly");
    setWeekInterval(1);
    setFormKind("routine");
    setShowCreateMenu(false);
    setError("");
  }

  function openNewReminder() {
    setEditingRoutine(null);
    setEditingReminder(null);
    setFormKind("reminder");
    setShowCreateMenu(false);
    setError("");
  }

  function openEditRoutine(routine: Routine) {
    setEditingRoutine(routine);
    setEditingReminder(null);
    setRepeatUnit(routine.repeat_unit);
    setWeekInterval(routine.interval_weeks);
    setFormKind("routine");
    setError("");
  }

  function openEditReminder(reminder: Reminder) {
    setEditingReminder(reminder);
    setEditingRoutine(null);
    setFormKind("reminder");
    setError("");
  }

  async function saveRoutine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId) return;
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const payload = {
      title: ((form.get("title") as string | null) ?? "").trim(),
      description: (form.get("description") as string) || null,
      scope: (form.get("scope") as RoutineScope | null) ?? "personal",
      interval_weeks: repeatUnit === "daily" ? 1 : Number(form.get("interval_weeks") ?? 1),
      repeat_unit: repeatUnit,
      week_anchor_date: (form.get("week_anchor_date") as string | null) ?? todayIso(),
      reminder_timing: (form.get("reminder_timing") as RoutineReminderTiming) ?? "evening_before",
      is_critical: form.get("is_critical") === "on",
      pinned: form.get("pinned") === "on",
      start_date: (form.get("start_date") as string | null) ?? todayIso(),
      end_date: (form.get("end_date") as string) || null,
      member_ids: [],
    };
    try {
      if (editingRoutine) {
        await api.updateRoutine(activeHomeId, editingRoutine.id, {
          ...payload,
          enabled: editingRoutine.enabled,
          expected_updated_at: editingRoutine.updated_at,
        });
        setMessage("Routine updated.");
      } else {
        await api.createRoutine(activeHomeId, payload);
        setMessage("Routine created.");
      }
      closeForms();
      await loadRoutines();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveReminder(event: FormEvent<HTMLFormElement>) {
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
      if (editingReminder) {
        await api.updateReminder(activeHomeId, editingReminder.id, {
          ...payload,
          enabled: editingReminder.enabled,
          expected_updated_at: editingReminder.updated_at,
        });
        setMessage("Reminder updated.");
      } else {
        await api.createReminder(activeHomeId, payload);
        setMessage("Reminder created.");
      }
      closeForms();
      await loadReminders();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function removeRoutine(routine: Routine) {
    if (!activeHomeId) return;
    if (!window.confirm(`Delete "${routine.title}"? This cannot be undone.`)) return;
    setError("");
    try {
      await api.deleteRoutine(activeHomeId, routine.id);
      await loadRoutines();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function removeReminder(reminder: Reminder) {
    if (!activeHomeId) return;
    if (!window.confirm(`Delete "${reminder.title}"? This cannot be undone.`)) return;
    setError("");
    try {
      await api.deleteReminder(activeHomeId, reminder.id);
      await loadReminders();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  // Completion dispatches to the correct source API by item kind — a Routine
  // occurrence-complete leaves future occurrences untouched, a one-off
  // Reminder complete stops it nagging for good, and a repeating Reminder
  // complete only closes the current occurrence. Nothing here reimplements
  // that semantics; it just calls the existing per-domain endpoint.
  async function toggleRoutine(routine: Routine) {
    if (!activeHomeId || !routine.next_occurrence_date) return;
    setError("");
    try {
      if (routine.completed_today) {
        await api.uncompleteRoutine(activeHomeId, routine.id, routine.next_occurrence_date);
      } else {
        await api.completeRoutine(activeHomeId, routine.id, routine.next_occurrence_date);
      }
      await loadRoutines();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function toggleReminder(reminder: Reminder) {
    if (!activeHomeId || !reminder.next_occurrence_date) return;
    const previous = reminders;
    setReminders((value) =>
      value.map((item) =>
        item.id === reminder.id ? { ...item, completed_today: !reminder.completed_today } : item,
      ),
    );
    setError("");
    try {
      if (reminder.completed_today) {
        await api.uncompleteReminder(activeHomeId, reminder.id, reminder.next_occurrence_date);
      } else {
        await api.completeReminder(activeHomeId, reminder.id, reminder.next_occurrence_date);
      }
      await loadReminders();
    } catch (cause) {
      setReminders(previous);
      setError((cause as Error).message);
    }
  }

  function toggleItem(item: UiItem) {
    if (item.kind === "routine") void toggleRoutine(item.data);
    else void toggleReminder(item.data);
  }

  const today = todayIso();

  const allItems: UiItem[] = useMemo(
    () => [
      ...routines.map((data): UiItem => ({ kind: "routine", id: `routine:${data.id}`, data })),
      ...reminders.map((data): UiItem => ({ kind: "reminder", id: `reminder:${data.id}`, data })),
    ],
    [routines, reminders],
  );

  const scopeFiltered = useMemo(
    () => allItems.filter((item) => item.data.scope === scopeTab),
    [allItems, scopeTab],
  );

  const typeFiltered = useMemo(
    () =>
      scopeFiltered.filter((item) => {
        if (typeTab === "routines") return item.kind === "routine";
        if (typeTab === "reminders") return item.kind === "reminder";
        return true;
      }),
    [scopeFiltered, typeTab],
  );

  const sections = useMemo(() => {
    const groups: Record<Section, UiItem[]> = { overdue: [], today: [], upcoming: [], completed: [] };
    for (const item of typeFiltered) {
      const section = sectionFor(item, today);
      if (section) groups[section].push(item);
    }
    for (const key of Object.keys(groups) as Section[]) groups[key].sort(compareItems);
    return groups;
  }, [typeFiltered, today]);

  function renderRow(item: UiItem) {
    const canManage = item.kind === "routine" ? canManageRoutines : canManageReminders;
    const completed = item.data.completed_today;
    return (
      <div className="rr-row" key={item.id}>
        <button
          className="rr-row-check"
          type="button"
          aria-label={`${completed ? "Completed" : "Complete"} ${item.data.title}`}
          aria-pressed={completed}
          disabled={completed || !item.data.next_occurrence_date}
          onClick={() => toggleItem(item)}
        >
          <span className="rr-row-check-dot" aria-hidden="true" />
        </button>
        <div className="rr-row-body">
          <strong className={completed ? "rr-row-done" : undefined}>{item.data.title}</strong>
          {item.data.description && <p>{item.data.description}</p>}
          <small>
            <span className="rr-row-kind">{item.kind === "routine" ? "Routine" : "Reminder"}</span>
            {" · "}
            {itemMetaLabel(item).replace(/^(Routine|Reminder) · /, "")}
            {!item.data.enabled ? " · Disabled" : ""}
          </small>
        </div>
        {canManage && (
          <div className="rr-row-actions">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                item.kind === "routine" ? openEditRoutine(item.data) : openEditReminder(item.data)
              }
            >
              Edit
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                item.kind === "routine" ? removeRoutine(item.data) : removeReminder(item.data)
              }
            >
              Delete
            </button>
          </div>
        )}
      </div>
    );
  }

  const sectionTitles: Record<Section, string> = {
    overdue: "Overdue",
    today: "Today",
    upcoming: "Upcoming",
    completed: "Completed",
  };

  const canManageAny = canManageRoutines || canManageReminders;
  const scopeWord = scopeTab === "household" ? "household" : "personal";
  const typeWord = typeTab === "all" ? "items" : typeTab;

  return (
    <SettingsPage title="Routines & Reminders">
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

      <div className="rr-tabs" role="group" aria-label="Filter by type">
        {(["all", "routines", "reminders"] as TypeFilter[]).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={typeTab === value}
            className={typeTab === value ? "toggle-active" : "secondary"}
            onClick={() => selectTypeTab(value)}
          >
            {value === "all" ? "All" : value === "routines" ? "Routines" : "Reminders"}
          </button>
        ))}
      </div>

      <div className="routine-choice" role="group" aria-label="Personal or household">
        {(["personal", "household"] as RoutineScope[]).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={scopeTab === value}
            className={scopeTab === value ? "toggle-active" : "secondary"}
            onClick={() => setScopeTab(value)}
          >
            {value === "personal" ? "Personal" : "Household"}
          </button>
        ))}
      </div>

      {(["overdue", "today", "upcoming", "completed"] as Section[]).map((section) =>
        sections[section].length > 0 ? (
          <section key={section}>
            <h2>{sectionTitles[section]}</h2>
            <div className="rr-list">{sections[section].map(renderRow)}</div>
          </section>
        ) : null,
      )}

      {typeFiltered.length === 0 && allItems.length > 0 && (
        <p>No {scopeWord} {typeWord} yet.</p>
      )}
      {allItems.length === 0 && (
        <p>
          Nothing here yet. Create a Routine for something you do regularly, or a Reminder for
          something you simply need to remember.
        </p>
      )}

      {canManageAny && formKind === null && (
        <div className="rr-create">
          <button type="button" onClick={() => setShowCreateMenu((value) => !value)}>
            Add
          </button>
          {showCreateMenu && (
            <div className="rr-create-menu" role="group" aria-label="Create">
              {typeTab === "reminders" ? (
                <>
                  {canManageReminders && (
                    <button type="button" onClick={openNewReminder}>
                      New Reminder
                    </button>
                  )}
                  {canManageRoutines && (
                    <button type="button" className="secondary" onClick={openNewRoutine}>
                      New Routine
                    </button>
                  )}
                </>
              ) : (
                <>
                  {canManageRoutines && (
                    <button type="button" onClick={openNewRoutine}>
                      New Routine
                    </button>
                  )}
                  {canManageReminders && (
                    <button type="button" className="secondary" onClick={openNewReminder}>
                      New Reminder
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {formKind === "routine" && (
        <form className="card details routine-form" key={editingRoutine?.id ?? "new-routine"} onSubmit={saveRoutine}>
          <h2>{editingRoutine ? "Edit routine" : "New routine"}</h2>
          <fieldset>
            <legend>Routine</legend>
            <label>
              Title
              <input name="title" required maxLength={160} defaultValue={editingRoutine?.title ?? ""} />
            </label>
            <label>
              Description (optional)
              <input name="description" maxLength={1000} defaultValue={editingRoutine?.description ?? ""} />
            </label>
          </fieldset>
          <fieldset>
            <legend>Schedule</legend>
            <label>
              Who this is for
              <select
                name="scope"
                defaultValue={editingRoutine?.scope ?? (householdRoutinesEnabled ? scopeTab : "personal")}
              >
                <option
                  value="household"
                  disabled={!householdRoutinesEnabled && editingRoutine?.scope !== "household"}
                >
                  {SCOPE_LABELS.household}
                  {!householdRoutinesEnabled && editingRoutine?.scope !== "household" ? " (Family)" : ""}
                </option>
                <option value="personal">{SCOPE_LABELS.personal}</option>
              </select>
            </label>
            {!householdRoutinesEnabled && (
              <FamilyUpsell
                title="Household routines"
                description="Available with MyKhaya Family — reminds everyone in the household, not just you."
              />
            )}
            <div className="routine-choice" role="group" aria-label="Repeat frequency">
              <span className="routine-choice-label">Repeat</span>
              {(["daily", "weekly"] as RoutineRepeatUnit[]).map((unit) => (
                <button
                  key={unit}
                  type="button"
                  aria-pressed={repeatUnit === unit}
                  className={repeatUnit === unit ? "toggle-active" : "secondary"}
                  onClick={() => setRepeatUnit(unit)}
                >
                  {unit === "daily" ? "Daily" : "Weekly"}
                </button>
              ))}
            </div>
            {repeatUnit === "weekly" && (
              <label>
                Every
                <select
                  name="interval_weeks"
                  value={weekInterval}
                  onChange={(event) => setWeekInterval(Number(event.target.value))}
                >
                  <option value={1}>1 week</option>
                  <option value={2}>2 weeks</option>
                  <option value={3}>3 weeks</option>
                  <option value={4}>4 weeks</option>
                </select>
              </label>
            )}
            <label>
              {repeatUnit === "daily" ? "Start date" : "Anchor date"}
              <input type="date" name="week_anchor_date" required defaultValue={editingRoutine?.week_anchor_date ?? todayIso()} />
              <small>{repeatUnit === "daily" ? "Repeats every day from this date." : "Choose a date when this routine occurs."}</small>
            </label>
            <label>
              Remind
              <select name="reminder_timing" defaultValue={editingRoutine?.reminder_timing ?? "evening_before"}>
                <option value="evening_before">{TIMING_LABELS.evening_before}</option>
                <option value="same_day">{TIMING_LABELS.same_day}</option>
                <option value="both">{TIMING_LABELS.both}</option>
              </select>
            </label>
            <div className="routine-date-grid">
              <label>
                Starts
                <input type="date" name="start_date" required defaultValue={editingRoutine?.start_date ?? todayIso()} />
              </label>
              <label>
                Ends (optional)
                <input type="date" name="end_date" defaultValue={editingRoutine?.end_date ?? ""} />
              </label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Notifications & Home</legend>
            <label className="routine-setting">
              <input type="checkbox" name="is_critical" defaultChecked={editingRoutine?.is_critical ?? false} />
              <span>
                <strong>Critical reminder</strong>
                <small>Can bypass quiet hours for medication and other important routines.</small>
              </span>
            </label>
            <label className="routine-setting">
              <input type="checkbox" name="pinned" defaultChecked={editingRoutine?.pinned ?? false} />
              <span>
                <strong>Pin to Home checklist</strong>
                <small>Keep this routine visible on your Home screen.</small>
              </span>
            </label>
          </fieldset>
          <div className="routine-form-actions">
            <button disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" className="secondary" onClick={closeForms}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {formKind === "reminder" && (
        <form className="card details routine-form" key={editingReminder?.id ?? "new-reminder"} onSubmit={saveReminder}>
          <h2>{editingReminder ? "Edit reminder" : "New reminder"}</h2>
          <fieldset>
            <legend>Reminder</legend>
            <label>
              Title
              <input name="title" required maxLength={160} defaultValue={editingReminder?.title ?? ""} />
            </label>
            <label>
              Notes (optional)
              <input name="description" maxLength={1000} defaultValue={editingReminder?.description ?? ""} />
            </label>
          </fieldset>
          <fieldset>
            <legend>Who</legend>
            <label>
              Scope
              <select name="scope" defaultValue={editingReminder?.scope ?? scopeTab}>
                <option value="personal">Personal — only reminds you</option>
                <option value="household">Household — reminds the home</option>
              </select>
            </label>
            <label>
              Assign to (household only)
              <select name="assignee" defaultValue={editingReminder?.member_ids[0] ?? ""}>
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
                <input type="date" name="due_date" required defaultValue={editingReminder?.due_date ?? today} />
              </label>
              <label>
                Due time
                <input type="time" name="due_time" required defaultValue={editingReminder?.due_time.slice(0, 5) ?? "09:00"} />
              </label>
            </div>
            <label>
              Repeat
              <select name="repeat" defaultValue={editingReminder?.repeat ?? "never"}>
                <option value="never">{REPEAT_LABELS.never}</option>
                <option value="daily">{REPEAT_LABELS.daily}</option>
                <option value="weekly">{REPEAT_LABELS.weekly}</option>
              </select>
            </label>
            <label>
              Remind
              <select name="cadence" defaultValue={editingReminder?.cadence ?? "once"}>
                <option value="once">{CADENCE_LABELS.once}</option>
                <option value="hourly">{CADENCE_LABELS.hourly}</option>
                <option value="daily">{CADENCE_LABELS.daily}</option>
                <option value="weekly">{CADENCE_LABELS.weekly}</option>
              </select>
            </label>
          </fieldset>
          <div className="routine-form-actions">
            <button disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" className="secondary" onClick={closeForms}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </SettingsPage>
  );
}
