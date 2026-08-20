"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ChefHat,
  ChevronLeft,
  ChevronRight,
  Clock,
  Pencil,
  Plus,
  Star,
  Trash2,
  UtensilsCrossed,
  X,
} from "lucide-react";
import type {
  BillingStatus,
  Meal,
  MealIngredientInput,
  MealPlanEntry,
  MealSlot,
  MealType,
  Member,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar, AvatarStack } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

// Meal Plans is a native MyKhaya module, not a bolted-on mini-app — this
// page reuses AppShell, BottomSheet, Avatar/AvatarStack, .card/.button/
// .member-list and the existing FamilyUpsell paid-gate pattern throughout,
// exactly as the other modules (Calendar, Routines) do. See
// docs/architecture/meal-plans.md for the full set of reuse decisions this
// was built against, including why "Add ingredients to list" is not present
// in this first iteration (MyKhaya has no Lists module yet).

const SLOTS: { key: MealSlot; label: string }[] = [
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" },
];

const MEAL_TYPES: { key: MealType; label: string }[] = [
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" },
  { key: "snack", label: "Snack" },
  { key: "dessert", label: "Dessert" },
  { key: "other", label: "Other" },
];

const WEEKDAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

// Meal dates/times are plain wall-clock values (no timezone conversion —
// see MealPlanEntry.date/time in the backend model) — so date arithmetic
// here is pure calendar-date maths on the "YYYY-MM-DD" string, the same
// UTC-midnight-anchored technique calendar-utils.ts already uses for
// all-day event boundaries, never a real instant/timezone conversion.
function isoToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
function startOfWeek(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  const offset = (date.getUTCDay() + 6) % 7; // Monday-anchored, matching Calendar's week view
  return addDays(iso, -offset);
}
function dayHeading(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}
function dayNumber(iso: string): number {
  return Number(iso.slice(8, 10));
}
function formatTime(value: string | null): string | null {
  if (!value) return null;
  return value.slice(0, 5);
}

function entryTitle(entry: MealPlanEntry): string {
  return entry.meal_name ?? entry.quick_meal_name ?? "Meal";
}

function memberNamesFor(memberIds: string[], members: Member[]): string {
  const names = memberIds
    .map((id) => members.find((member) => member.user_id === id)?.display_name)
    .filter((name): name is string => Boolean(name));
  if (names.length === 0) return "";
  if (names.length === members.length && members.length > 0) return "Everyone";
  return names.join(", ");
}

export default function MealPlansPage() {
  const { activeHomeId } = useActiveHome();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [tab, setTab] = useState<"plan" | "meals">("plan");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    api.billingStatus(activeHomeId).then(setBilling).catch(() => setBilling(null));
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId]);

  if (!activeHomeId || !billing) {
    return (
      <AppShell>
        <main className="standard-page">
          <p role="status">Loading Meal Plans…</p>
        </main>
      </AppShell>
    );
  }

  if (!billing.meals_enabled) {
    return (
      <AppShell>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Meal Plans</p>
              <h1>Meal Plans</h1>
            </div>
          </div>
          <FamilyUpsell
            title="Meal Plans"
            description="Plan meals together, save family favourites and turn ingredients into shopping lists. Included with Family."
          />
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <main className="standard-page meal-plans-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              <UtensilsCrossed size={14} aria-hidden="true" /> Meal Plans
            </p>
            <h1>Meal Plans</h1>
          </div>
        </div>
        <FormStatus error={error} />
        <div className="meal-tabs" role="tablist" aria-label="Meal Plans sections">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "plan"}
            className={tab === "plan" ? "toggle-active" : "secondary"}
            onClick={() => setTab("plan")}
          >
            Plan
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "meals"}
            className={tab === "meals" ? "toggle-active" : "secondary"}
            onClick={() => setTab("meals")}
          >
            Meals
          </button>
        </div>
        {tab === "plan" ? (
          <PlannerTab homeId={activeHomeId} members={members} onError={setError} />
        ) : (
          <MealsLibraryTab homeId={activeHomeId} onError={setError} />
        )}
      </main>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// Planner tab: single-day vertical planner (default) + a Week overview.
// ---------------------------------------------------------------------------

function PlannerTab({
  homeId,
  members,
  onError,
}: {
  homeId: string;
  members: Member[];
  onError: (message: string) => void;
}) {
  const [view, setView] = useState<"day" | "week">("day");
  const [focusDate, setFocusDate] = useState(isoToday());
  const [dayEntries, setDayEntries] = useState<MealPlanEntry[]>([]);
  const [weekDays, setWeekDays] = useState<{ date: string; entries: MealPlanEntry[] }[]>([]);
  const [sheet, setSheet] = useState<
    | { mode: "view"; entry: MealPlanEntry }
    | { mode: "edit"; entry: MealPlanEntry }
    | { mode: "create"; date: string; slot: MealSlot }
    | null
  >(null);

  async function loadDay() {
    try {
      const result = await api.mealPlanDay(homeId, focusDate);
      setDayEntries(result.entries);
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not load your meal plan.");
    }
  }
  async function loadWeek() {
    try {
      const result = await api.mealPlanWeek(homeId, startOfWeek(focusDate));
      setWeekDays(result.days);
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not load your meal plan.");
    }
  }

  useEffect(() => {
    if (view === "day") void loadDay();
    else void loadWeek();
  }, [homeId, focusDate, view]);

  async function refresh() {
    if (view === "day") await loadDay();
    else await loadWeek();
  }

  async function removeEntry(entry: MealPlanEntry) {
    if (!window.confirm(`Remove ${entryTitle(entry)} from the plan?`)) return;
    try {
      await api.deleteMealPlanEntry(homeId, entry.id);
      setSheet(null);
      await refresh();
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not remove that meal.");
    }
  }

  const week = useMemo(() => {
    const start = startOfWeek(focusDate);
    return Array.from({ length: 7 }, (_, index) => addDays(start, index));
  }, [focusDate]);

  return (
    <section>
      <header className="calendar-toolbar-compact meal-plan-toolbar">
        <div className="calendar-month-row">
          <button
            className="icon-button secondary"
            type="button"
            onClick={() => setFocusDate(addDays(focusDate, view === "day" ? -1 : -7))}
            aria-label={view === "day" ? "Previous day" : "Previous week"}
          >
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
          <strong>{view === "day" ? dayHeading(focusDate) : `Week of ${dayHeading(week[0]!)}`}</strong>
          <button
            className="icon-button secondary"
            type="button"
            onClick={() => setFocusDate(addDays(focusDate, view === "day" ? 1 : 7))}
            aria-label={view === "day" ? "Next day" : "Next week"}
          >
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="meal-plan-toolbar-actions">
          {focusDate !== isoToday() && (
            <button type="button" className="tertiary" onClick={() => setFocusDate(isoToday())}>
              Today
            </button>
          )}
          <label className="calendar-selector">
            <span className="sr-only">View</span>
            <select value={view} onChange={(event) => setView(event.target.value as "day" | "week")}>
              <option value="day">Day</option>
              <option value="week">Week</option>
            </select>
          </label>
        </div>
      </header>

      {view === "day" && (
        <div className="week-strip" role="tablist" aria-label="Choose a day">
          {week.map((iso, index) => (
            <button
              key={iso}
              type="button"
              role="tab"
              aria-selected={iso === focusDate}
              className={`week-strip-day${iso === focusDate ? " active" : ""}${iso === isoToday() ? " today" : ""}`}
              onClick={() => setFocusDate(iso)}
            >
              <span className="week-strip-letter">{WEEKDAY_LETTERS[index]}</span>
              <span className="week-strip-number">{dayNumber(iso)}</span>
            </button>
          ))}
        </div>
      )}

      {view === "day" ? (
        <div className="meal-slot-list">
          {SLOTS.map((slot) => (
            <div className="meal-slot-section" key={slot.key}>
              <h2>{slot.label}</h2>
              {dayEntries
                .filter((entry) => entry.meal_slot === slot.key)
                .map((entry) => (
                  <MealEntryCard
                    key={entry.id}
                    entry={entry}
                    members={members}
                    onOpen={() => setSheet({ mode: "view", entry })}
                  />
                ))}
              <button
                type="button"
                className="meal-add-button"
                onClick={() => setSheet({ mode: "create", date: focusDate, slot: slot.key })}
              >
                <Plus size={16} aria-hidden="true" /> Add
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="meal-week-list">
          {weekDays.map((day) => (
            <div className="card meal-week-day" key={day.date}>
              <h2>{dayHeading(day.date)}</h2>
              {SLOTS.map((slot) => {
                const entry = day.entries.find((row) => row.meal_slot === slot.key);
                return (
                  <button
                    type="button"
                    className="meal-week-row"
                    key={slot.key}
                    onClick={() =>
                      entry
                        ? setSheet({ mode: "view", entry })
                        : setSheet({ mode: "create", date: day.date, slot: slot.key })
                    }
                  >
                    <span className="meal-week-slot">{slot.label}</span>
                    <span className="meal-week-name">
                      {entry ? entryTitle(entry) : <span className="quiet-state">+ Add</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {sheet && (
        <MealEntrySheet
          homeId={homeId}
          members={members}
          state={sheet}
          onClose={() => setSheet(null)}
          onEdit={(entry) => setSheet({ mode: "edit", entry })}
          onDelete={removeEntry}
          onSaved={async () => {
            setSheet(null);
            await refresh();
          }}
        />
      )}
    </section>
  );
}

function MealEntryCard({
  entry,
  members,
  onOpen,
}: {
  entry: MealPlanEntry;
  members: Member[];
  onOpen: () => void;
}) {
  const time = formatTime(entry.time);
  const stackPeople = entry.member_ids
    .map((id) => members.find((member) => member.user_id === id))
    .filter((member): member is Member => Boolean(member));
  const cook = members.find((member) => member.user_id === entry.cook_member_id);
  return (
    <button type="button" className="card meal-entry-card" onClick={onOpen}>
      <div className="meal-entry-main">
        <div className="meal-entry-heading">
          <strong>{entryTitle(entry)}</strong>
          {entry.is_favourite && <Star size={14} aria-hidden="true" className="meal-favourite-star" />}
        </div>
        <div className="meal-entry-meta">
          {time && (
            <span>
              <Clock size={13} aria-hidden="true" /> {time}
            </span>
          )}
          {stackPeople.length > 0 && <span>{memberNamesFor(entry.member_ids, members)}</span>}
          {cook && (
            <span>
              <ChefHat size={13} aria-hidden="true" /> {cook.display_name} cooking
            </span>
          )}
          {entry.makes_leftovers && <span className="quiet-state">Leftovers</span>}
        </div>
      </div>
      {stackPeople.length > 0 && <AvatarStack people={stackPeople} size="sm" />}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Add/Edit/View Meal Plan entry — one BottomSheet for all three modes.
// ---------------------------------------------------------------------------

function MealEntrySheet({
  homeId,
  members,
  state,
  onClose,
  onEdit,
  onDelete,
  onSaved,
}: {
  homeId: string;
  members: Member[];
  state:
    | { mode: "view"; entry: MealPlanEntry }
    | { mode: "edit"; entry: MealPlanEntry }
    | { mode: "create"; date: string; slot: MealSlot };
  onClose: () => void;
  onEdit: (entry: MealPlanEntry) => void;
  onDelete: (entry: MealPlanEntry) => void;
  onSaved: () => Promise<void>;
}) {
  const [savedMeals, setSavedMeals] = useState<Meal[]>([]);
  const [source, setSource] = useState<"saved" | "quick">(
    state.mode !== "create" && state.entry.meal_id ? "saved" : "quick",
  );
  const [mealId, setMealId] = useState(state.mode !== "create" ? (state.entry.meal_id ?? "") : "");
  const [quickName, setQuickName] = useState(
    state.mode !== "create" ? (state.entry.quick_meal_name ?? "") : "",
  );
  const [date, setDate] = useState(state.mode === "create" ? state.date : state.entry.date);
  const [slot, setSlot] = useState<MealSlot>(state.mode === "create" ? state.slot : state.entry.meal_slot);
  const [time, setTime] = useState(state.mode !== "create" ? formatTime(state.entry.time) ?? "" : "");
  const [everyone, setEveryone] = useState(
    state.mode === "create" || state.entry.member_ids.length === members.length,
  );
  const [memberIds, setMemberIds] = useState<string[]>(
    state.mode !== "create" ? state.entry.member_ids : members.map((member) => member.user_id),
  );
  const [cookId, setCookId] = useState(state.mode !== "create" ? (state.entry.cook_member_id ?? "") : "");
  const [leftovers, setLeftovers] = useState(state.mode !== "create" ? state.entry.makes_leftovers : false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.meals(homeId).then((result) => setSavedMeals(result.items)).catch(() => setSavedMeals([]));
  }, [homeId]);

  if (state.mode === "view") {
    const entry = state.entry;
    const time = formatTime(entry.time);
    const cook = members.find((member) => member.user_id === entry.cook_member_id);
    const people = entry.member_ids
      .map((id) => members.find((member) => member.user_id === id))
      .filter((member): member is Member => Boolean(member));
    return (
      <BottomSheet
        title={entryTitle(entry)}
        onDismiss={onClose}
        headerAction={
          <button
            type="button"
            className="icon-button secondary"
            onClick={() => onEdit(entry)}
            aria-label="Edit meal"
          >
            <Pencil size={16} aria-hidden="true" />
          </button>
        }
      >
        <div className="meal-view-details">
          {entry.is_favourite && (
            <p className="quiet-state">
              <Star size={14} aria-hidden="true" /> Favourite
            </p>
          )}
          {time && (
            <p>
              <Clock size={14} aria-hidden="true" /> {time}
            </p>
          )}
          {people.length > 0 && (
            <div className="meal-view-people">
              <AvatarStack people={people} size="sm" />
              <span>{memberNamesFor(entry.member_ids, members)}</span>
            </div>
          )}
          {cook && (
            <p>
              <ChefHat size={14} aria-hidden="true" /> {cook.display_name} cooking
            </p>
          )}
          {entry.makes_leftovers && <p className="quiet-state">Makes leftovers</p>}
          <button type="button" className="secondary" onClick={() => onDelete(entry)}>
            <Trash2 size={16} aria-hidden="true" /> Remove from plan
          </button>
        </div>
      </BottomSheet>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (source === "saved" && !mealId) {
      setError("Choose a saved meal, or switch to Quick meal.");
      return;
    }
    if (source === "quick" && !quickName.trim()) {
      setError("Enter a name for this meal.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        meal_id: source === "saved" ? mealId : null,
        quick_meal_name: source === "quick" ? quickName.trim() : null,
        date,
        meal_slot: slot,
        time: time || null,
        member_ids: everyone ? undefined : memberIds,
        cook_member_id: cookId || null,
        makes_leftovers: leftovers,
      };
      if (state.mode === "edit") {
        await api.updateMealPlanEntry(homeId, state.entry.id, {
          ...payload,
          expected_updated_at: state.entry.updated_at,
        });
      } else {
        await api.createMealPlanEntry(homeId, payload);
      }
      await onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this meal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title={state.mode === "edit" ? "Edit meal" : "Add meal"} onDismiss={onClose}>
      <form onSubmit={submit}>
        <div className="meal-source-toggle">
          <button
            type="button"
            className={source === "saved" ? "toggle-active" : "secondary"}
            onClick={() => setSource("saved")}
          >
            Saved meal
          </button>
          <button
            type="button"
            className={source === "quick" ? "toggle-active" : "secondary"}
            onClick={() => setSource("quick")}
          >
            Quick meal
          </button>
        </div>
        {source === "saved" ? (
          <label>
            Meal
            <select value={mealId} onChange={(event) => setMealId(event.target.value)}>
              <option value="">Choose a saved meal…</option>
              {savedMeals.map((meal) => (
                <option key={meal.id} value={meal.id}>
                  {meal.is_favourite ? "★ " : ""}
                  {meal.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            What's for {SLOTS.find((row) => row.key === slot)?.label.toLowerCase()}?
            <input
              value={quickName}
              onChange={(event) => setQuickName(event.target.value)}
              placeholder="e.g. Takeaway, School lunch, Leftovers"
              maxLength={160}
            />
          </label>
        )}
        <div className="meal-form-row">
          <label>
            Date
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
          </label>
          <label>
            Meal
            <select value={slot} onChange={(event) => setSlot(event.target.value as MealSlot)}>
              {SLOTS.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Time (optional)
            <input type="time" value={time} onChange={(event) => setTime(event.target.value)} />
          </label>
        </div>

        <span className="eyebrow">Who's eating</span>
        <label className="check-row">
          <input
            type="checkbox"
            checked={everyone}
            onChange={(event) => {
              setEveryone(event.target.checked);
              if (event.target.checked) setMemberIds(members.map((member) => member.user_id));
            }}
          />
          Everyone
        </label>
        {!everyone && (
          <div className="member-list">
            {members.map((member) => (
              <label className="member-row" key={member.user_id}>
                <Avatar
                  id={member.user_id}
                  name={member.display_name}
                  colour={member.colour}
                  avatarVersion={member.avatar_version}
                  size="sm"
                />
                <span className="member-row-name">{member.display_name}</span>
                <input
                  type="checkbox"
                  checked={memberIds.includes(member.user_id)}
                  onChange={(event) =>
                    setMemberIds((current) =>
                      event.target.checked
                        ? [...current, member.user_id]
                        : current.filter((id) => id !== member.user_id),
                    )
                  }
                  aria-label={`Include ${member.display_name}`}
                />
              </label>
            ))}
          </div>
        )}

        <label>
          Cooking (optional)
          <select value={cookId} onChange={(event) => setCookId(event.target.value)}>
            <option value="">No one set</option>
            {members.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.display_name}
              </option>
            ))}
          </select>
        </label>

        <label className="check-row">
          <input
            type="checkbox"
            checked={leftovers}
            onChange={(event) => setLeftovers(event.target.checked)}
          />
          Makes leftovers
        </label>

        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </form>
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// Meals library tab
// ---------------------------------------------------------------------------

function MealsLibraryTab({ homeId, onError }: { homeId: string; onError: (message: string) => void }) {
  const [meals, setMeals] = useState<Meal[]>([]);
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Meal | "new" | null>(null);
  const [planning, setPlanning] = useState<Meal | null>(null);

  async function load() {
    try {
      const result = await api.meals(homeId, {
        favourite: favouritesOnly || undefined,
        q: query || undefined,
      });
      setMeals(result.items);
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not load your meals.");
    }
  }

  useEffect(() => {
    const timeout = setTimeout(() => void load(), 200);
    return () => clearTimeout(timeout);
  }, [homeId, favouritesOnly, query]);

  async function toggleFavourite(meal: Meal) {
    try {
      await api.setMealFavourite(homeId, meal.id, !meal.is_favourite);
      await load();
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not update that meal.");
    }
  }

  async function removeMeal(meal: Meal) {
    if (!window.confirm(`Delete ${meal.name}? Any past or planned entries keep its name.`)) return;
    try {
      await api.deleteMeal(homeId, meal.id);
      await load();
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "Could not delete that meal.");
    }
  }

  return (
    <section>
      <div className="meal-library-toolbar">
        <input
          type="search"
          placeholder="Search your meals…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search meals"
        />
        <label className="check-row">
          <input
            type="checkbox"
            checked={favouritesOnly}
            onChange={(event) => setFavouritesOnly(event.target.checked)}
          />
          Favourites
        </label>
        <button type="button" onClick={() => setEditing("new")}>
          <Plus size={16} aria-hidden="true" /> Add meal
        </button>
      </div>

      {meals.length === 0 ? (
        <p className="empty-mini">
          No meals saved yet. Add your family favourites to plan them again in a couple of taps.
        </p>
      ) : (
        <div className="meal-library-grid">
          {meals.map((meal) => (
            <article className="card meal-library-card" key={meal.id}>
              <div className="meal-library-heading">
                <h3>{meal.name}</h3>
                <button
                  type="button"
                  className="icon-button secondary"
                  onClick={() => void toggleFavourite(meal)}
                  aria-label={meal.is_favourite ? "Remove favourite" : "Mark favourite"}
                  aria-pressed={meal.is_favourite}
                >
                  <Star
                    size={16}
                    aria-hidden="true"
                    className={meal.is_favourite ? "meal-favourite-star" : ""}
                  />
                </button>
              </div>
              <p className="quiet-state">
                {MEAL_TYPES.find((row) => row.key === meal.meal_type)?.label}
                {meal.servings ? ` · Serves ${meal.servings}` : ""}
                {meal.cook_minutes ? ` · ${meal.cook_minutes} min` : ""}
              </p>
              {meal.description && <p className="muted">{meal.description}</p>}
              <div className="meal-library-actions">
                <button type="button" className="secondary" onClick={() => setPlanning(meal)}>
                  Plan meal
                </button>
                <button type="button" className="tertiary" onClick={() => setEditing(meal)}>
                  <Pencil size={14} aria-hidden="true" /> Edit
                </button>
                <button type="button" className="tertiary" onClick={() => void removeMeal(meal)}>
                  <Trash2 size={14} aria-hidden="true" /> Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {editing && (
        <MealFormSheet
          homeId={homeId}
          meal={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await load();
          }}
        />
      )}
      {planning && (
        <PlanFromMealSheet homeId={homeId} meal={planning} onClose={() => setPlanning(null)} />
      )}
    </section>
  );
}

function MealFormSheet({
  homeId,
  meal,
  onClose,
  onSaved,
}: {
  homeId: string;
  meal: Meal | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(meal?.name ?? "");
  const [description, setDescription] = useState(meal?.description ?? "");
  const [mealType, setMealType] = useState<MealType>(meal?.meal_type ?? "dinner");
  const [prepMinutes, setPrepMinutes] = useState(meal?.prep_minutes?.toString() ?? "");
  const [cookMinutes, setCookMinutes] = useState(meal?.cook_minutes?.toString() ?? "");
  const [servings, setServings] = useState(meal?.servings?.toString() ?? "");
  const [instructions, setInstructions] = useState(meal?.instructions ?? "");
  const [tags, setTags] = useState(meal?.tags.join(", ") ?? "");
  const [isFavourite, setIsFavourite] = useState(meal?.is_favourite ?? false);
  const [ingredients, setIngredients] = useState<MealIngredientInput[]>(
    meal?.ingredients.map((row) => ({ text: row.text, quantity: row.quantity, unit: row.unit })) ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function updateIngredient(index: number, patch: Partial<MealIngredientInput>) {
    setIngredients((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give this meal a name.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        meal_type: mealType,
        prep_minutes: prepMinutes ? Number(prepMinutes) : null,
        cook_minutes: cookMinutes ? Number(cookMinutes) : null,
        servings: servings ? Number(servings) : null,
        instructions: instructions.trim() || null,
        is_favourite: isFavourite,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        ingredients: ingredients.filter((row) => row.text.trim()),
      };
      if (meal) {
        await api.updateMeal(homeId, meal.id, { ...payload, expected_updated_at: meal.updated_at });
      } else {
        await api.createMeal(homeId, payload);
      }
      await onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this meal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title={meal ? "Edit meal" : "Add meal"} onDismiss={onClose} fullHeight>
      <form onSubmit={submit}>
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={160} required />
        </label>
        <label>
          Description (optional)
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={2000}
          />
        </label>
        <div className="meal-form-row">
          <label>
            Category
            <select value={mealType} onChange={(event) => setMealType(event.target.value as MealType)}>
              {MEAL_TYPES.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Servings
            <input
              type="number"
              min={1}
              value={servings}
              onChange={(event) => setServings(event.target.value)}
            />
          </label>
        </div>
        <div className="meal-form-row">
          <label>
            Prep (minutes)
            <input
              type="number"
              min={0}
              value={prepMinutes}
              onChange={(event) => setPrepMinutes(event.target.value)}
            />
          </label>
          <label>
            Cook (minutes)
            <input
              type="number"
              min={0}
              value={cookMinutes}
              onChange={(event) => setCookMinutes(event.target.value)}
            />
          </label>
        </div>

        <span className="eyebrow">Ingredients</span>
        <div className="meal-ingredient-list">
          {ingredients.map((row, index) => (
            <div className="meal-ingredient-row" key={index}>
              <input
                placeholder="Qty"
                value={row.quantity ?? ""}
                onChange={(event) => updateIngredient(index, { quantity: event.target.value })}
                className="meal-ingredient-qty"
              />
              <input
                placeholder="Unit"
                value={row.unit ?? ""}
                onChange={(event) => updateIngredient(index, { unit: event.target.value })}
                className="meal-ingredient-unit"
              />
              <input
                placeholder="Ingredient"
                value={row.text}
                onChange={(event) => updateIngredient(index, { text: event.target.value })}
                className="meal-ingredient-text"
              />
              <button
                type="button"
                className="icon-button secondary"
                aria-label="Remove ingredient"
                onClick={() => setIngredients((current) => current.filter((_, i) => i !== index))}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="tertiary"
          onClick={() => setIngredients((current) => [...current, { text: "", quantity: "", unit: "" }])}
        >
          <Plus size={14} aria-hidden="true" /> Add ingredient
        </button>

        <label>
          Method (optional)
          <textarea
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            maxLength={8000}
          />
        </label>
        <label>
          Tags (optional, comma separated)
          <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="midweek, kids' favourite" />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={isFavourite}
            onChange={(event) => setIsFavourite(event.target.checked)}
          />
          Favourite
        </label>

        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Saving…" : "Save meal"}</button>
      </form>
    </BottomSheet>
  );
}

function PlanFromMealSheet({
  homeId,
  meal,
  onClose,
}: {
  homeId: string;
  meal: Meal;
  onClose: () => void;
}) {
  const [date, setDate] = useState(isoToday());
  const [slot, setSlot] = useState<MealSlot>(
    meal.meal_type === "breakfast" || meal.meal_type === "lunch" || meal.meal_type === "dinner"
      ? meal.meal_type
      : "dinner",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createMealPlanEntry(homeId, { meal_id: meal.id, date, meal_slot: slot });
      setDone(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add this to your plan.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title={`Plan ${meal.name}`} onDismiss={onClose}>
      {done ? (
        <p className="notice success" role="status">
          {meal.name} was added to your plan.
        </p>
      ) : (
        <form onSubmit={submit}>
          <div className="meal-form-row">
            <label>
              Date
              <input
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                required
              />
            </label>
            <label>
              Meal
              <select value={slot} onChange={(event) => setSlot(event.target.value as MealSlot)}>
                {SLOTS.map((row) => (
                  <option key={row.key} value={row.key}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <FormStatus error={error} />
          <button disabled={busy}>{busy ? "Adding…" : "Add to plan"}</button>
        </form>
      )}
    </BottomSheet>
  );
}
