"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CalendarDays,
  ChefHat,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  ListPlus,
  MoreVertical,
  Pencil,
  Plus,
  Star,
  Trash2,
  Users,
  UtensilsCrossed,
  X,
} from "lucide-react";
import type {
  AddIngredientsToListResult,
  BillingStatus,
  HouseholdList,
  Meal,
  MealIngredient,
  MealIngredientInput,
  MealPlanEntry,
  MealSlot,
  MealSummary,
  MealType,
  Member,
  RecentMeal,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { Avatar, AvatarStack } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useDaySwipe } from "./use-day-swipe";

// Meal Plans is a native MyKhaya module, not a bolted-on mini-app — this
// page reuses AppShell, BottomSheet, Avatar/AvatarStack, .card/.button/
// .member-list and the existing FamilyUpsell paid-gate pattern throughout,
// exactly as the other modules (Calendar, Routines) do. See
// docs/architecture/meal-plans.md. "Add ingredients to list" now targets
// mykhaya.routers.lists' HouseholdList — MyKhaya's one shared-list
// primitive, added alongside this iteration rather than a second,
// meal-specific shopping-list implementation.

const SLOTS: {
  key: MealSlot;
  label: string;
  subtitle: string;
  icon: string;
}[] = [
  {
    key: "breakfast",
    label: "Breakfast",
    subtitle: "Start the day well",
    icon: "/images/meal-plans-breakfast.png",
  },
  {
    key: "lunch",
    label: "Lunch",
    subtitle: "Keep everyone fuelled",
    icon: "/images/meal-plans-lunch.png",
  },
  {
    key: "dinner",
    label: "Dinner",
    subtitle: "Good food, great company",
    icon: "/images/meal-plans-dinner.png",
  },
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

const QUICK_MEAL_PLACEHOLDERS: Record<MealSlot, string> = {
  breakfast: "e.g. Overnight oats, Toast, Cereal",
  lunch: "e.g. Sandwiches, School lunch, Leftovers",
  dinner: "e.g. Lasagne, Takeaway, Leftovers",
};

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
  return date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
function dayNumber(iso: string): number {
  return Number(iso.slice(8, 10));
}
function formatTime(value: string | null): string | null {
  if (!value) return null;
  return value.slice(0, 5);
}
// Calendar-date subtraction, not a Date.now() wall-clock diff — comparing
// "now" (whatever time of day it happens to be) against a date's UTC
// midnight would round today itself up to "Yesterday" once the clock
// passes noon UTC. Both sides are anchored at UTC midnight instead, the
// same convention addDays/startOfWeek already use.
function daysSince(iso: string): number {
  const today = new Date(`${isoToday()}T00:00:00Z`).getTime();
  const then = new Date(`${iso}T00:00:00Z`).getTime();
  return Math.round((today - then) / 86_400_000);
}
function relativeWeeksAgo(iso: string): string {
  const days = daysSince(iso);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 14) return `${days} days ago`;
  const weeks = Math.round(days / 7);
  return `${weeks} week${weeks === 1 ? "" : "s"} ago`;
}

function entryTitle(entry: MealPlanEntry): string {
  return entry.meal_name ?? entry.quick_meal_name ?? "Meal";
}

function ingredientLine(
  ingredient: MealIngredient | MealIngredientInput,
): string {
  return [ingredient.quantity, ingredient.unit, ingredient.text]
    .filter(Boolean)
    .join(" ");
}

// What PlanFromMealSheet actually needs — satisfied by both the library's
// lightweight MealSummary and a full Meal (from the detail sheet), so
// "Plan this meal" works from either without forcing a shared shape.
type PlannableMeal = Pick<MealSummary, "id" | "name" | "meal_type">;

// A 404 here means the Meal Plans module itself isn't switched on for this
// Home yet (a separate, Platform-Admin-controlled release gate ahead of the
// Family/Free entitlement check this page already handles via
// FamilyUpsell) — a real but different situation from "your request
// failed", so it gets its own calm message rather than surfacing the raw
// backend "Not found" detail as a technical-looking error banner.
function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "Meal Plans isn't available for this Home yet. Please check back soon.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
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
  // The frontend's Family/Free gate (billing.meals_enabled) and the
  // backend's separate Platform-Admin release gate (require_feature) used
  // to disagree silently — a Family Home could see the full interactive
  // planner while every request 404'd underneath it (see
  // docs/architecture/meal-plans.md "Migration-head safety" incident
  // report). Checking the same feature matrix the Home shortcut already
  // uses closes that gap here too, rather than duplicating a second
  // feature-state check.
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [tab, setTab] = useState<"plan" | "meals">("plan");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then(setBilling)
      .catch(() => setBilling(null));
    api
      .members(activeHomeId)
      .then(setMembers)
      .catch(() => setMembers([]));
    api
      .featureMatrix(activeHomeId)
      .then((matrix) =>
        setModuleReleased(
          matrix.features.some((row) => row.feature === "meals" && row.enabled),
        ),
      )
      .catch(() => setModuleReleased(false));
  }, [activeHomeId]);

  if (!activeHomeId || !billing || moduleReleased === null) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading Meal Plans…</p>
        </main>
      </AppShellContent>
    );
  }

  if (!billing.meals_enabled) {
    return (
      <AppShellContent>
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
      </AppShellContent>
    );
  }

  if (!moduleReleased) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Meal Plans</p>
              <h1>Meal Plans</h1>
            </div>
          </div>
          <p className="empty-mini">
            Meal Plans isn't available for this Home yet. Please check back
            soon.
          </p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page meal-plans-page">
        <div className="page-heading meal-plans-hero">
          <div className="meal-plans-hero-text">
            <p className="eyebrow">
              <UtensilsCrossed size={14} aria-hidden="true" /> Meal Plans
            </p>
            <h1>Meal Plans</h1>
            <p className="muted">
              Plan, cook and enjoy mealtimes together.
            </p>
          </div>
          <img
            className="meal-plans-hero-art"
            src="/images/meal-plans-good-food.png"
            alt="Good food, happier days"
            width={640}
            height={387}
          />
        </div>
        <FormStatus error={error} />
        <div
          className="meal-tabs"
          role="tablist"
          aria-label="Meal Plans sections"
        >
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
          <PlannerTab
            homeId={activeHomeId}
            members={members}
            onError={setError}
          />
        ) : (
          <MealsLibraryTab homeId={activeHomeId} onError={setError} />
        )}
      </main>
    </AppShellContent>
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
  const [weekDays, setWeekDays] = useState<
    { date: string; entries: MealPlanEntry[] }[]
  >([]);
  const [sheet, setSheet] = useState<
    | { mode: "view"; entry: MealPlanEntry }
    | { mode: "edit"; entry: MealPlanEntry }
    | { mode: "create"; date: string; slot: MealSlot }
    | null
  >(null);
  const [copyingWeek, setCopyingWeek] = useState(false);
  const [addingIngredientsFor, setAddingIngredientsFor] = useState<
    string | null
  >(null);
  const [editingMealId, setEditingMealId] = useState<string | null>(null);

  async function loadDay() {
    try {
      const result = await api.mealPlanDay(homeId, focusDate);
      setDayEntries(result.entries);
    } catch (cause) {
      onError(loadErrorMessage(cause, "Could not load your meal plan."));
    }
  }
  async function loadWeek() {
    try {
      const result = await api.mealPlanWeek(homeId, startOfWeek(focusDate));
      setWeekDays(result.days);
    } catch (cause) {
      onError(loadErrorMessage(cause, "Could not load your meal plan."));
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
      onError(
        cause instanceof ApiError
          ? cause.message
          : "Could not remove that meal.",
      );
    }
  }

  async function saveAsMeal(entry: MealPlanEntry) {
    try {
      await api.saveMealPlanEntryAsMeal(homeId, entry.id);
      setSheet(null);
      await refresh();
    } catch (cause) {
      onError(
        cause instanceof ApiError
          ? cause.message
          : "Could not save this to your Meals library.",
      );
    }
  }

  const week = useMemo(() => {
    const start = startOfWeek(focusDate);
    return Array.from({ length: 7 }, (_, index) => addDays(start, index));
  }, [focusDate]);

  const daySwipeHandlers = useDaySwipe({
    onSwipeLeft: () => setFocusDate((current) => addDays(current, 1)),
    onSwipeRight: () => setFocusDate((current) => addDays(current, -1)),
    disabled: view !== "day",
  });

  return (
    <section>
      <header className="meal-plans-toolbar">
        <div className="meal-plans-date-nav">
          <button
            className="icon-button secondary"
            type="button"
            onClick={() =>
              setFocusDate(addDays(focusDate, view === "day" ? -1 : -7))
            }
            aria-label={view === "day" ? "Previous day" : "Previous week"}
          >
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
          <strong className="meal-plan-date-pill">
            <CalendarDays size={15} aria-hidden="true" />
            {view === "day"
              ? dayHeading(focusDate)
              : `Week of ${dayHeading(week[0]!)}`}
          </strong>
          <button
            className="icon-button secondary"
            type="button"
            onClick={() =>
              setFocusDate(addDays(focusDate, view === "day" ? 1 : 7))
            }
            aria-label={view === "day" ? "Next day" : "Next week"}
          >
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="meal-plans-toolbar-right">
          {focusDate !== isoToday() && (
            <button
              type="button"
              className="tertiary meal-plans-today-button"
              onClick={() => setFocusDate(isoToday())}
            >
              Today
            </button>
          )}
          <div
            className="meal-view-toggle meal-plans-view-toggle"
            role="tablist"
            aria-label="Choose view"
          >
            <button
              type="button"
              role="tab"
              aria-selected={view === "day"}
              className={view === "day" ? "toggle-active" : "secondary"}
              onClick={() => setView("day")}
            >
              Day
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "week"}
              className={view === "week" ? "toggle-active" : "secondary"}
              onClick={() => setView("week")}
            >
              Week
            </button>
          </div>
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
              <span className="week-strip-letter">
                {WEEKDAY_LETTERS[index]}
              </span>
              <span className="week-strip-number">{dayNumber(iso)}</span>
            </button>
          ))}
        </div>
      )}

      {view === "day" ? (
        <div className="meal-day-swipe-surface" {...daySwipeHandlers}>
          <div className="meal-slot-list">
            {SLOTS.map((slot) => (
              <div className="card meal-slot-section" key={slot.key}>
                <div className="meal-slot-heading">
                  <img
                    className="meal-slot-icon"
                    src={slot.icon}
                    alt=""
                    aria-hidden="true"
                    width={32}
                    height={32}
                  />
                  <div>
                    <h2>{slot.label}</h2>
                    <p className="meal-slot-subtitle">{slot.subtitle}</p>
                  </div>
                </div>
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
                  onClick={() =>
                    setSheet({
                      mode: "create",
                      date: focusDate,
                      slot: slot.key,
                    })
                  }
                >
                  <span className="meal-add-icon">
                    <Plus size={16} aria-hidden="true" />
                  </span>
                  Add
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <button
            type="button"
            className="tertiary meal-copy-week-button"
            onClick={() => setCopyingWeek(true)}
          >
            <Copy size={14} aria-hidden="true" /> Copy previous week
          </button>
          <div className="meal-week-list">
            {weekDays.map((day) => (
              <div className="card meal-week-day" key={day.date}>
                <h2>{dayHeading(day.date)}</h2>
                {SLOTS.map((slot) => {
                  const entry = day.entries.find(
                    (row) => row.meal_slot === slot.key,
                  );
                  return (
                    <button
                      type="button"
                      className="meal-week-row"
                      key={slot.key}
                      onClick={() =>
                        entry
                          ? setSheet({ mode: "view", entry })
                          : setSheet({
                              mode: "create",
                              date: day.date,
                              slot: slot.key,
                            })
                      }
                    >
                      <span className="meal-week-slot">{slot.label}</span>
                      <span className="meal-week-name">
                        {entry ? (
                          entryTitle(entry)
                        ) : (
                          <span className="quiet-state">+ Add</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </>
      )}

      {sheet && (
        <MealEntrySheet
          homeId={homeId}
          members={members}
          state={sheet}
          onClose={() => setSheet(null)}
          onEdit={(entry) => setSheet({ mode: "edit", entry })}
          onDelete={removeEntry}
          onSaveAsMeal={saveAsMeal}
          onAddIngredients={(mealId) => setAddingIngredientsFor(mealId)}
          onEditMeal={(mealId) => setEditingMealId(mealId)}
          onSaved={async () => {
            setSheet(null);
            await refresh();
          }}
        />
      )}
      {addingIngredientsFor && (
        <AddIngredientsToListSheet
          homeId={homeId}
          mealId={addingIngredientsFor}
          onClose={() => setAddingIngredientsFor(null)}
        />
      )}
      {editingMealId && (
        <MealFormSheet
          homeId={homeId}
          mealId={editingMealId}
          onClose={() => setEditingMealId(null)}
          onSaved={async () => {
            setEditingMealId(null);
            await refresh();
          }}
        />
      )}
      {copyingWeek && (
        <CopyPreviousWeekSheet
          homeId={homeId}
          targetStartDate={startOfWeek(focusDate)}
          onClose={() => setCopyingWeek(false)}
          // Refreshes the plan in the background but leaves the sheet open
          // — it shows its own "N meals copied" confirmation, and closing
          // it immediately would mean the user never sees that result.
          onCopied={refresh}
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
  const cook = members.find(
    (member) => member.user_id === entry.cook_member_id,
  );
  return (
    <button type="button" className="card meal-entry-card" onClick={onOpen}>
      {entry.meal_image_url && (
        <img className="meal-entry-thumb" src={entry.meal_image_url} alt="" />
      )}
      <div className="meal-entry-main">
        <div className="meal-entry-heading">
          <strong className="text-clamp-2">{entryTitle(entry)}</strong>
          {entry.is_favourite && (
            <Star
              size={14}
              aria-hidden="true"
              className="meal-favourite-star"
            />
          )}
        </div>
        <div className="meal-entry-meta">
          {time && (
            <span>
              <Clock size={13} aria-hidden="true" /> {time}
            </span>
          )}
          {stackPeople.length > 0 && (
            <span>
              <Users size={13} aria-hidden="true" />{" "}
              {memberNamesFor(entry.member_ids, members)}
            </span>
          )}
          {cook && (
            <span>
              <ChefHat size={13} aria-hidden="true" /> {cook.display_name}{" "}
              cooking
            </span>
          )}
          {entry.makes_leftovers && (
            <span className="quiet-state">Leftovers</span>
          )}
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
  onSaveAsMeal,
  onAddIngredients,
  onEditMeal,
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
  onSaveAsMeal: (entry: MealPlanEntry) => void;
  onAddIngredients: (mealId: string) => void;
  onEditMeal: (mealId: string) => void;
  onSaved: () => Promise<void>;
}) {
  const [savedMeals, setSavedMeals] = useState<MealSummary[]>([]);
  const [source, setSource] = useState<"saved" | "quick">(
    state.mode !== "create" && state.entry.meal_id ? "saved" : "quick",
  );
  const [mealId, setMealId] = useState(
    state.mode !== "create" ? (state.entry.meal_id ?? "") : "",
  );
  const [quickName, setQuickName] = useState(
    state.mode !== "create" ? (state.entry.quick_meal_name ?? "") : "",
  );
  const [date, setDate] = useState(
    state.mode === "create" ? state.date : state.entry.date,
  );
  const [slot, setSlot] = useState<MealSlot>(
    state.mode === "create" ? state.slot : state.entry.meal_slot,
  );
  const [time, setTime] = useState(
    state.mode !== "create" ? (formatTime(state.entry.time) ?? "") : "",
  );
  const [everyone, setEveryone] = useState(
    state.mode === "create" || state.entry.member_ids.length === members.length,
  );
  const [memberIds, setMemberIds] = useState<string[]>(
    state.mode !== "create"
      ? state.entry.member_ids
      : members.map((member) => member.user_id),
  );
  const [cookId, setCookId] = useState(
    state.mode !== "create" ? (state.entry.cook_member_id ?? "") : "",
  );
  const [leftovers, setLeftovers] = useState(
    state.mode !== "create" ? state.entry.makes_leftovers : false,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .meals(homeId)
      .then((result) => setSavedMeals(result.items))
      .catch(() => setSavedMeals([]));
  }, [homeId]);

  if (state.mode === "view") {
    const entry = state.entry;
    const time = formatTime(entry.time);
    const cook = members.find(
      (member) => member.user_id === entry.cook_member_id,
    );
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
          {entry.meal_image_url && (
            <img
              className="meal-view-image"
              src={entry.meal_image_url}
              alt=""
            />
          )}
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
              <ChefHat size={14} aria-hidden="true" /> {cook.display_name}{" "}
              cooking
            </p>
          )}
          {entry.makes_leftovers && (
            <p className="quiet-state">Makes leftovers</p>
          )}

          <div className="meal-view-actions">
            {entry.meal_id ? (
              <>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onAddIngredients(entry.meal_id!)}
                >
                  <ListPlus size={16} aria-hidden="true" /> Add ingredients to
                  list
                </button>
                <button
                  type="button"
                  className="tertiary"
                  onClick={() => onEditMeal(entry.meal_id!)}
                >
                  <Pencil size={14} aria-hidden="true" /> Edit saved meal
                </button>
              </>
            ) : (
              entry.quick_meal_name && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onSaveAsMeal(entry)}
                >
                  <Star size={16} aria-hidden="true" /> Save to Meals
                </button>
              )
            )}
          </div>

          {/* Removing this occurrence from the plan is a distinct action
              from deleting the saved Meal it references — that lives only
              in the Meals library's own overflow menu, never here. */}
          <button
            type="button"
            className="secondary"
            onClick={() => onDelete(entry)}
          >
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
      setError(
        cause instanceof ApiError ? cause.message : "Could not save this meal.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet
      title={state.mode === "edit" ? "Edit meal" : "Add meal"}
      onDismiss={onClose}
    >
      <form className="event-form" onSubmit={submit}>
        <div className="form-wide meal-source-toggle">
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
          <label className="form-wide">
            Meal
            <select
              value={mealId}
              onChange={(event) => setMealId(event.target.value)}
            >
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
          <label className="form-wide">
            What's for{" "}
            {SLOTS.find((row) => row.key === slot)?.label.toLowerCase()}?
            <input
              value={quickName}
              onChange={(event) => setQuickName(event.target.value)}
              placeholder={QUICK_MEAL_PLACEHOLDERS[slot]}
              maxLength={160}
            />
          </label>
        )}

        <label className="form-wide">
          Date
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            required
          />
        </label>
        <div className="form-wide meal-time-row">
          <label>
            Meal
            <select
              value={slot}
              onChange={(event) => setSlot(event.target.value as MealSlot)}
            >
              {SLOTS.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Time (optional)
            <input
              type="time"
              value={time}
              onChange={(event) => setTime(event.target.value)}
            />
          </label>
        </div>

        <div className="form-wide event-section">
          <span className="eyebrow">Who's eating</span>
          <label className="check-row">
            <input
              type="checkbox"
              checked={everyone}
              onChange={(event) => {
                setEveryone(event.target.checked);
                if (event.target.checked)
                  setMemberIds(members.map((member) => member.user_id));
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
        </div>

        <label className="form-wide">
          Cooking (optional)
          <select
            value={cookId}
            onChange={(event) => setCookId(event.target.value)}
          >
            <option value="">No one set</option>
            {members.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.display_name}
              </option>
            ))}
          </select>
        </label>

        <label className="check-row form-wide">
          <input
            type="checkbox"
            checked={leftovers}
            onChange={(event) => setLeftovers(event.target.checked)}
          />
          Makes leftovers
        </label>

        <div className="form-wide">
          <FormStatus error={error} />
        </div>
        <button className="sheet-primary form-wide" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      </form>
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// Copy previous week
// ---------------------------------------------------------------------------

function CopyPreviousWeekSheet({
  homeId,
  targetStartDate,
  onClose,
  onCopied,
}: {
  homeId: string;
  targetStartDate: string;
  onClose: () => void;
  onCopied: () => Promise<void>;
}) {
  const sourceStartDate = addDays(targetStartDate, -7);
  const [preview, setPreview] = useState<{
    copied: number;
    skipped: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ copied: number; skipped: number } | null>(
    null,
  );

  useEffect(() => {
    api
      .copyMealPlanWeek(homeId, {
        source_start_date: sourceStartDate,
        target_start_date: targetStartDate,
        dry_run: true,
      })
      .then((result) =>
        setPreview({
          copied: result.copied_count,
          skipped: result.skipped_count,
        }),
      )
      .catch((cause) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : "Could not preview last week's plan.",
        ),
      );
  }, [homeId, sourceStartDate, targetStartDate]);

  async function confirmCopy() {
    setBusy(true);
    setError("");
    try {
      const result = await api.copyMealPlanWeek(homeId, {
        source_start_date: sourceStartDate,
        target_start_date: targetStartDate,
      });
      setDone({ copied: result.copied_count, skipped: result.skipped_count });
      await onCopied();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not copy last week's plan.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="Copy previous week" onDismiss={onClose}>
      {done ? (
        <p className="notice success" role="status">
          {done.copied} meal{done.copied === 1 ? "" : "s"} copied.
          {done.skipped > 0 &&
            ` ${done.skipped} existing meal${done.skipped === 1 ? "" : "s"} left unchanged.`}
        </p>
      ) : (
        <div className="meal-view-details">
          {preview ? (
            preview.copied === 0 ? (
              <p className="empty-mini">
                {sourceStartDate} to {addDays(sourceStartDate, 6)} has nothing
                planned to copy.
              </p>
            ) : (
              <p>
                This will copy {preview.copied} planned meal
                {preview.copied === 1 ? "" : "s"} from{" "}
                {dayHeading(sourceStartDate)}–
                {dayHeading(addDays(sourceStartDate, 6))} into{" "}
                {dayHeading(targetStartDate)}–
                {dayHeading(addDays(targetStartDate, 6))}.
                {preview.skipped > 0 && (
                  <>
                    {" "}
                    {preview.skipped} day/slot{preview.skipped === 1 ? "" : "s"}{" "}
                    already planned won't be overwritten.
                  </>
                )}
              </p>
            )
          ) : (
            <p role="status">Checking last week's plan…</p>
          )}
          <FormStatus error={error} />
          <div className="meal-copy-week-actions">
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="sheet-primary"
              disabled={busy || !preview || preview.copied === 0}
              onClick={() => void confirmCopy()}
            >
              {busy ? "Copying…" : "Copy week"}
            </button>
          </div>
        </div>
      )}
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// Add ingredients to a Household List
// ---------------------------------------------------------------------------

function AddIngredientsToListSheet({
  homeId,
  mealId,
  onClose,
}: {
  homeId: string;
  mealId: string;
  onClose: () => void;
}) {
  const [meal, setMeal] = useState<Meal | null>(null);
  const [lists, setLists] = useState<HouseholdList[]>([]);
  const [listId, setListId] = useState("");
  const [newListName, setNewListName] = useState("");
  const [creatingList, setCreatingList] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmState, setConfirmState] =
    useState<AddIngredientsToListResult | null>(null);
  const [result, setResult] = useState<AddIngredientsToListResult | null>(null);

  useEffect(() => {
    api
      .meal(homeId, mealId)
      .then((row) => {
        setMeal(row);
        setSelected(
          new Set(row.ingredients.map((ingredient) => ingredient.id)),
        );
      })
      .catch(() => setMeal(null));
    api
      .lists(homeId)
      .then((response) => {
        setLists(response.items);
        if (response.items.length > 0) setListId(response.items[0]!.id);
        else setCreatingList(true);
      })
      .catch(() => setLists([]));
  }, [homeId, mealId]);

  async function createList() {
    if (!newListName.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await api.createList(homeId, {
        name: newListName.trim(),
      });
      setLists((current) => [
        ...current,
        { ...created, item_count: 0, remaining_count: 0 },
      ]);
      setListId(created.id);
      setCreatingList(false);
      setNewListName("");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not create that list.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function addIngredients(confirm: boolean) {
    if (!listId) {
      setError("Choose a list first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api.addIngredientsToList(homeId, mealId, {
        list_id: listId,
        ingredient_ids: Array.from(selected),
        confirm,
      });
      if (response.requires_confirmation) {
        setConfirmState(response);
      } else {
        setConfirmState(null);
        setResult(response);
      }
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not add these ingredients.",
      );
    } finally {
      setBusy(false);
    }
  }

  const listName = lists.find((row) => row.id === listId)?.name ?? "your list";

  if (meal && meal.ingredients.length === 0) {
    return (
      <BottomSheet title="Add ingredients to list" onDismiss={onClose}>
        <p className="empty-mini">
          This meal doesn't have any ingredients yet.
        </p>
      </BottomSheet>
    );
  }

  if (result) {
    return (
      <BottomSheet title="Add ingredients to list" onDismiss={onClose}>
        <p className="notice success" role="status">
          Added {result.added_count} item{result.added_count === 1 ? "" : "s"}{" "}
          to {listName}.
          {result.duplicate_count > 0 &&
            ` ${result.duplicate_count} ${result.duplicate_count === 1 ? "was" : "were"} already there.`}
        </p>
        <div className="meal-copy-week-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Done
          </button>
          <Link
            className="button sheet-primary"
            href={`/lists/${result.list_id}`}
          >
            View {listName}
          </Link>
        </div>
      </BottomSheet>
    );
  }

  if (confirmState) {
    return (
      <BottomSheet title="Some items already exist" onDismiss={onClose}>
        <div className="meal-view-details">
          <p>
            {confirmState.duplicate_count} item
            {confirmState.duplicate_count === 1 ? " is" : "s are"} already on{" "}
            {listName}.
          </p>
          <ul className="meal-duplicate-list">
            {confirmState.duplicate_texts.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <p>
            Add the remaining {selected.size - confirmState.duplicate_count}
            {selected.size - confirmState.duplicate_count === 1
              ? " item"
              : " items"}
            ?
          </p>
          <FormStatus error={error} />
          <div className="meal-copy-week-actions">
            <button
              type="button"
              className="secondary"
              onClick={() => setConfirmState(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="sheet-primary"
              disabled={busy}
              onClick={() => void addIngredients(true)}
            >
              {busy ? "Adding…" : "Add remaining"}
            </button>
          </div>
        </div>
      </BottomSheet>
    );
  }

  return (
    <BottomSheet title="Add ingredients to list" onDismiss={onClose}>
      <div className="meal-view-details">
        <label>
          Choose list
          {creatingList || lists.length === 0 ? (
            <div className="meal-time-row">
              <input
                value={newListName}
                onChange={(event) => setNewListName(event.target.value)}
                placeholder="e.g. Groceries"
                maxLength={160}
              />
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => void createList()}
              >
                Create
              </button>
            </div>
          ) : (
            <select
              value={listId}
              onChange={(event) => {
                if (event.target.value === "__new__") setCreatingList(true);
                else setListId(event.target.value);
              }}
            >
              {lists.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
              <option value="__new__">+ New list…</option>
            </select>
          )}
        </label>

        <span className="eyebrow">Ingredients</span>
        {!meal ? (
          <p role="status">Loading…</p>
        ) : (
          <div className="meal-ingredient-checklist">
            {meal.ingredients.map((ingredient) => (
              <label className="check-row" key={ingredient.id}>
                <input
                  type="checkbox"
                  checked={selected.has(ingredient.id)}
                  onChange={(event) =>
                    setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(ingredient.id);
                      else next.delete(ingredient.id);
                      return next;
                    })
                  }
                />
                {ingredientLine(ingredient)}
              </label>
            ))}
          </div>
        )}

        <FormStatus error={error} />
        <button
          type="button"
          className="sheet-primary"
          disabled={
            busy || selected.size === 0 || !listId || listId === "__new__"
          }
          onClick={() => void addIngredients(false)}
        >
          {busy
            ? "Adding…"
            : `Add ${selected.size} item${selected.size === 1 ? "" : "s"}`}
        </button>
      </div>
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// Meals library tab
// ---------------------------------------------------------------------------

function MealsLibraryTab({
  homeId,
  onError,
}: {
  homeId: string;
  onError: (message: string) => void;
}) {
  const [meals, setMeals] = useState<MealSummary[]>([]);
  const [recent, setRecent] = useState<RecentMeal[]>([]);
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [query, setQuery] = useState("");
  // "" is the sentinel for "creating a new meal" — distinct from null
  // (sheet closed) and from any real meal id (editing that meal).
  const [editingMealId, setEditingMealId] = useState<string | null>(null);
  const [viewingMealId, setViewingMealId] = useState<string | null>(null);
  const [planning, setPlanning] = useState<PlannableMeal | null>(null);
  const [actionsFor, setActionsFor] = useState<MealSummary | null>(null);
  const [addingIngredientsFor, setAddingIngredientsFor] = useState<
    string | null
  >(null);

  async function load() {
    try {
      const result = await api.meals(homeId, {
        favourite: favouritesOnly || undefined,
        q: query || undefined,
      });
      setMeals(result.items);
    } catch (cause) {
      onError(loadErrorMessage(cause, "Could not load your meals."));
    }
  }

  async function loadRecent() {
    try {
      const result = await api.recentMeals(homeId, 5);
      setRecent(result.items);
    } catch {
      setRecent([]);
    }
  }

  useEffect(() => {
    const timeout = setTimeout(() => void load(), 200);
    return () => clearTimeout(timeout);
  }, [homeId, favouritesOnly, query]);

  useEffect(() => {
    void loadRecent();
  }, [homeId]);

  async function toggleFavourite(meal: MealSummary) {
    try {
      await api.setMealFavourite(homeId, meal.id, !meal.is_favourite);
      setActionsFor(null);
      await load();
    } catch (cause) {
      onError(
        cause instanceof ApiError
          ? cause.message
          : "Could not update that meal.",
      );
    }
  }

  async function removeMeal(meal: MealSummary) {
    if (
      !window.confirm(
        `Delete ${meal.name}? Any past or planned entries keep its name.`,
      )
    )
      return;
    try {
      await api.deleteMeal(homeId, meal.id);
      setActionsFor(null);
      await load();
      await loadRecent();
    } catch (cause) {
      onError(
        cause instanceof ApiError
          ? cause.message
          : "Could not delete that meal.",
      );
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
        <button type="button" onClick={() => setEditingMealId("")}>
          <Plus size={16} aria-hidden="true" /> Add meal
        </button>
      </div>
      <div
        className="meal-view-toggle meal-library-filter"
        role="tablist"
        aria-label="Filter meals"
      >
        <button
          type="button"
          role="tab"
          aria-selected={!favouritesOnly}
          className={!favouritesOnly ? "toggle-active" : "secondary"}
          onClick={() => setFavouritesOnly(false)}
        >
          All
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={favouritesOnly}
          className={favouritesOnly ? "toggle-active" : "secondary"}
          onClick={() => setFavouritesOnly(true)}
        >
          Favourites
        </button>
      </div>

      {!query && !favouritesOnly && recent.length > 0 && (
        <div className="meal-recent-section">
          <span className="eyebrow">Recently used</span>
          <div className="meal-recent-list">
            {recent.map((row) => (
              <button
                type="button"
                className="meal-recent-row"
                key={row.meal.id}
                onClick={() => setViewingMealId(row.meal.id)}
              >
                <span>{row.meal.name}</span>
                <span className="quiet-state">
                  Last planned {relativeWeeksAgo(row.last_planned)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {meals.length === 0 ? (
        query || favouritesOnly ? (
          <p className="empty-mini">No meals match.</p>
        ) : (
          <div className="meal-empty-state">
            <p>
              <strong>No saved meals yet</strong>
            </p>
            <p className="muted">
              Save family favourites so they're quick to plan again.
            </p>
            <button
              type="button"
              className="secondary"
              onClick={() => setEditingMealId("")}
            >
              <Plus size={16} aria-hidden="true" /> Add your first meal
            </button>
          </div>
        )
      ) : (
        <div className="meal-library-grid">
          {meals.map((meal) => (
            <article className="card meal-library-card" key={meal.id}>
              <button
                type="button"
                className="meal-library-card-body"
                onClick={() => setViewingMealId(meal.id)}
              >
                <div className="meal-library-heading">
                  <h3>{meal.name}</h3>
                  {meal.is_favourite && (
                    <Star
                      size={15}
                      aria-hidden="true"
                      className="meal-favourite-star"
                    />
                  )}
                </div>
                <p className="quiet-state">
                  {MEAL_TYPES.find((row) => row.key === meal.meal_type)?.label}
                  {meal.servings ? ` · Serves ${meal.servings}` : ""}
                  {meal.cook_minutes ? ` · ${meal.cook_minutes} min` : ""}
                </p>
              </button>
              <div className="meal-library-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPlanning(meal)}
                >
                  Plan meal
                </button>
                <button
                  type="button"
                  className="icon-button secondary"
                  aria-label={`More actions for ${meal.name}`}
                  onClick={() => setActionsFor(meal)}
                >
                  <MoreVertical size={16} aria-hidden="true" />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {actionsFor && (
        <MealActionsSheet
          meal={actionsFor}
          onClose={() => setActionsFor(null)}
          onEdit={() => {
            setEditingMealId(actionsFor.id);
            setActionsFor(null);
          }}
          onFavourite={() => void toggleFavourite(actionsFor)}
          onAddIngredients={() => {
            setAddingIngredientsFor(actionsFor.id);
            setActionsFor(null);
          }}
          onDelete={() => void removeMeal(actionsFor)}
        />
      )}
      {viewingMealId && (
        <MealDetailSheet
          homeId={homeId}
          mealId={viewingMealId}
          onClose={() => setViewingMealId(null)}
          onPlan={(meal) => {
            setPlanning(meal);
            setViewingMealId(null);
          }}
          onEdit={(meal) => {
            setEditingMealId(meal.id);
            setViewingMealId(null);
          }}
          onAddIngredients={(meal) => {
            setAddingIngredientsFor(meal.id);
            setViewingMealId(null);
          }}
        />
      )}
      {editingMealId !== null && (
        <MealFormSheet
          homeId={homeId}
          mealId={editingMealId || null}
          onClose={() => setEditingMealId(null)}
          onSaved={async () => {
            setEditingMealId(null);
            await load();
            await loadRecent();
          }}
        />
      )}
      {planning && (
        <PlanFromMealSheet
          homeId={homeId}
          meal={planning}
          onClose={() => setPlanning(null)}
        />
      )}
      {addingIngredientsFor && (
        <AddIngredientsToListSheet
          homeId={homeId}
          mealId={addingIngredientsFor}
          onClose={() => setAddingIngredientsFor(null)}
        />
      )}
    </section>
  );
}

function MealActionsSheet({
  meal,
  onClose,
  onEdit,
  onFavourite,
  onAddIngredients,
  onDelete,
}: {
  meal: MealSummary;
  onClose: () => void;
  onEdit: () => void;
  onFavourite: () => void;
  onAddIngredients: () => void;
  onDelete: () => void;
}) {
  return (
    <BottomSheet title={meal.name} onDismiss={onClose}>
      <div className="meal-actions-sheet">
        <button type="button" className="secondary" onClick={onEdit}>
          <Pencil size={16} aria-hidden="true" /> Edit
        </button>
        <button type="button" className="secondary" onClick={onFavourite}>
          <Star size={16} aria-hidden="true" />{" "}
          {meal.is_favourite ? "Unfavourite" : "Favourite"}
        </button>
        <button type="button" className="secondary" onClick={onAddIngredients}>
          <ListPlus size={16} aria-hidden="true" /> Add ingredients to list
        </button>
        <button type="button" className="secondary" onClick={onDelete}>
          <Trash2 size={16} aria-hidden="true" /> Delete
        </button>
      </div>
    </BottomSheet>
  );
}

function MealDetailSheet({
  homeId,
  mealId,
  onClose,
  onPlan,
  onEdit,
  onAddIngredients,
}: {
  homeId: string;
  mealId: string;
  onClose: () => void;
  onPlan: (meal: PlannableMeal) => void;
  onEdit: (meal: Meal) => void;
  onAddIngredients: (meal: Meal) => void;
}) {
  const [meal, setMeal] = useState<Meal | null>(null);

  useEffect(() => {
    api
      .meal(homeId, mealId)
      .then(setMeal)
      .catch(() => setMeal(null));
  }, [homeId, mealId]);

  if (!meal) {
    return (
      <BottomSheet title="Meal" onDismiss={onClose}>
        <p role="status">Loading…</p>
      </BottomSheet>
    );
  }

  return (
    <BottomSheet
      title={meal.name}
      onDismiss={onClose}
      headerAction={
        <button
          type="button"
          className="icon-button secondary"
          onClick={() => onEdit(meal)}
          aria-label="Edit meal"
        >
          <Pencil size={16} aria-hidden="true" />
        </button>
      }
      fullHeight
    >
      <div className="meal-view-details">
        {meal.image_url && (
          <img className="meal-view-image" src={meal.image_url} alt="" />
        )}
        <p className="quiet-state">
          {[
            meal.prep_minutes ? `${meal.prep_minutes} min prep` : null,
            meal.cook_minutes ? `${meal.cook_minutes} min cook` : null,
            meal.servings ? `Serves ${meal.servings}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {meal.is_favourite && (
          <p className="quiet-state">
            <Star size={14} aria-hidden="true" /> Favourite
          </p>
        )}
        {meal.description && <p className="muted">{meal.description}</p>}

        <span className="eyebrow">Ingredients</span>
        {meal.ingredients.length === 0 ? (
          <p className="empty-mini">No ingredients added yet.</p>
        ) : (
          <ul className="meal-ingredient-view-list">
            {meal.ingredients.map((ingredient) => (
              <li key={ingredient.id}>{ingredientLine(ingredient)}</li>
            ))}
          </ul>
        )}

        {meal.instructions && (
          <>
            <span className="eyebrow">Method</span>
            <p className="meal-instructions">{meal.instructions}</p>
          </>
        )}

        <button
          type="button"
          className="sheet-primary"
          onClick={() => onPlan(meal)}
        >
          Plan this meal
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => onAddIngredients(meal)}
        >
          <ListPlus size={16} aria-hidden="true" /> Add ingredients to list
        </button>
      </div>
    </BottomSheet>
  );
}

function MealFormSheet({
  homeId,
  mealId,
  onClose,
  onSaved,
}: {
  homeId: string;
  mealId: string | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [meal, setMeal] = useState<Meal | null>(null);
  const [loading, setLoading] = useState(Boolean(mealId));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [mealType, setMealType] = useState<MealType>("dinner");
  const [prepMinutes, setPrepMinutes] = useState("");
  const [cookMinutes, setCookMinutes] = useState("");
  const [servings, setServings] = useState("");
  const [instructions, setInstructions] = useState("");
  const [tags, setTags] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [isFavourite, setIsFavourite] = useState(false);
  const [ingredients, setIngredients] = useState<MealIngredientInput[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!mealId) {
      setLoading(false);
      return;
    }
    api
      .meal(homeId, mealId)
      .then((row) => {
        setMeal(row);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [homeId, mealId]);

  useEffect(() => {
    if (!meal) return;
    setName(meal.name);
    setDescription(meal.description ?? "");
    setImageUrl(meal.image_url ?? "");
    setMealType(meal.meal_type);
    setPrepMinutes(meal.prep_minutes?.toString() ?? "");
    setCookMinutes(meal.cook_minutes?.toString() ?? "");
    setServings(meal.servings?.toString() ?? "");
    setInstructions(meal.instructions ?? "");
    setTags(meal.tags.join(", "));
    setSourceUrl(meal.source_url ?? "");
    setIsFavourite(meal.is_favourite);
    setIngredients(
      meal.ingredients.map((row) => ({
        text: row.text,
        quantity: row.quantity,
        unit: row.unit,
      })),
    );
  }, [meal]);

  function updateIngredient(
    index: number,
    patch: Partial<MealIngredientInput>,
  ) {
    setIngredients((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row,
      ),
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
        image_url: imageUrl.trim() || null,
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
        source_url: sourceUrl.trim() || null,
        ingredients: ingredients.filter((row) => row.text.trim()),
      };
      if (meal) {
        await api.updateMeal(homeId, meal.id, {
          ...payload,
          expected_updated_at: meal.updated_at,
        });
      } else {
        await api.createMeal(homeId, payload);
      }
      await onSaved();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Could not save this meal.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <BottomSheet title="Meal" onDismiss={onClose}>
        <p role="status">Loading…</p>
      </BottomSheet>
    );
  }

  return (
    <BottomSheet
      title={meal ? "Edit meal" : "Add meal"}
      onDismiss={onClose}
      fullHeight
    >
      <form onSubmit={submit}>
        <label>
          Name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={160}
            required
          />
        </label>
        <div className="meal-form-row">
          <label>
            Category
            <select
              value={mealType}
              onChange={(event) => setMealType(event.target.value as MealType)}
            >
              {MEAL_TYPES.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row meal-favourite-field">
            <input
              type="checkbox"
              checked={isFavourite}
              onChange={(event) => setIsFavourite(event.target.checked)}
            />
            Favourite
          </label>
        </div>
        <label>
          Description (optional)
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={2000}
          />
        </label>

        <details className="event-advanced" open>
          <summary>
            <span className="event-advanced-lead">Timing &amp; servings</span>
            <ChevronRight className="chevron" size={18} aria-hidden="true" />
          </summary>
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
        </details>

        <details className="event-advanced" open>
          <summary>
            <span className="event-advanced-lead">Ingredients</span>
            <ChevronRight className="chevron" size={18} aria-hidden="true" />
          </summary>
          <div className="meal-ingredient-list">
            {ingredients.map((row, index) => (
              <div className="meal-ingredient-card" key={index}>
                <button
                  type="button"
                  className="icon-button secondary meal-ingredient-remove"
                  aria-label="Remove ingredient"
                  onClick={() =>
                    setIngredients((current) =>
                      current.filter((_, i) => i !== index),
                    )
                  }
                >
                  <X size={14} aria-hidden="true" />
                </button>
                <div className="meal-ingredient-qty-row">
                  <label>
                    <span className="hint">Quantity</span>
                    <input
                      placeholder="e.g. 500"
                      value={row.quantity ?? ""}
                      onChange={(event) =>
                        updateIngredient(index, {
                          quantity: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    <span className="hint">Unit</span>
                    <input
                      placeholder="e.g. g"
                      value={row.unit ?? ""}
                      onChange={(event) =>
                        updateIngredient(index, { unit: event.target.value })
                      }
                    />
                  </label>
                </div>
                <label>
                  <span className="hint">Ingredient</span>
                  <input
                    placeholder="e.g. Beef mince"
                    value={row.text}
                    onChange={(event) =>
                      updateIngredient(index, { text: event.target.value })
                    }
                  />
                </label>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="tertiary"
            onClick={() =>
              setIngredients((current) => [
                ...current,
                { text: "", quantity: "", unit: "" },
              ])
            }
          >
            <Plus size={14} aria-hidden="true" /> Add ingredient
          </button>
        </details>

        <details className="event-advanced">
          <summary>
            <span className="event-advanced-lead">Method</span>
            <ChevronRight className="chevron" size={18} aria-hidden="true" />
          </summary>
          <label>
            <span className="hint">Method (optional)</span>
            <textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              maxLength={8000}
            />
          </label>
        </details>

        <details className="event-advanced">
          <summary>
            <span className="event-advanced-lead">More details</span>
            <ChevronRight className="chevron" size={18} aria-hidden="true" />
          </summary>
          <label>
            <span className="hint">Photo URL (optional)</span>
            <input
              value={imageUrl}
              onChange={(event) => setImageUrl(event.target.value)}
              placeholder="https://…"
              maxLength={2000}
            />
          </label>
          <label>
            <span className="hint">Tags (optional, comma separated)</span>
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="midweek, kids' favourite"
            />
          </label>
          <label>
            <span className="hint">Source URL (optional)</span>
            <input
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              placeholder="https://…"
              maxLength={2000}
            />
          </label>
        </details>

        <FormStatus error={error} />
        <button className="sheet-primary" disabled={busy}>
          {busy ? "Saving…" : "Save meal"}
        </button>
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
  meal: PlannableMeal;
  onClose: () => void;
}) {
  const [date, setDate] = useState(isoToday());
  const [slot, setSlot] = useState<MealSlot>(
    meal.meal_type === "breakfast" ||
      meal.meal_type === "lunch" ||
      meal.meal_type === "dinner"
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
      await api.createMealPlanEntry(homeId, {
        meal_id: meal.id,
        date,
        meal_slot: slot,
      });
      setDone(true);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not add this to your plan.",
      );
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
        <form className="plan-meal-form" onSubmit={submit}>
          <div className="plan-meal-fields">
            <label>
              Date
              <span className="plan-meal-field">
                <CalendarDays
                  className="plan-meal-field-icon"
                  size={18}
                  aria-hidden="true"
                />
                <input
                  className="plan-meal-field-input"
                  type="date"
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                  required
                />
              </span>
            </label>
            <label>
              Meal
              <span className="plan-meal-field">
                <select
                  className="plan-meal-field-input"
                  value={slot}
                  onChange={(event) => setSlot(event.target.value as MealSlot)}
                >
                  {SLOTS.map((row) => (
                    <option key={row.key} value={row.key}>
                      {row.label}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  className="plan-meal-field-chevron"
                  size={16}
                  aria-hidden="true"
                />
              </span>
            </label>
          </div>
          {error && <FormStatus error={error} />}
          <button className="sheet-primary" disabled={busy}>
            {busy ? "Adding…" : "Add to plan"}
          </button>
        </form>
      )}
    </BottomSheet>
  );
}
