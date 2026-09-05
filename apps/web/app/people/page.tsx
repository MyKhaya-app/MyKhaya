"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronRight, Users } from "lucide-react";
import type {
  BirthdayEntry,
  HomeSummary,
  HouseholdRelationship,
  MealPlanEntry,
  Member,
  Reminder,
  Routine,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { participantsForEvent } from "@/components/avatar-stack-logic";
import { FamilyChatPreview } from "@/components/family-chat-preview";
import { useActiveHome } from "@/components/use-active-home";
import { isBirthdayThisMonthAndUpcoming } from "../home/birthday-utils";
import { localIsoDate, routineDueLabel } from "../home/routine-utils";

// The Family tab — a people-focused household overview. All administrative
// controls (invite, change relationship/colour, child privacy) live at
// /settings/members instead (reached from More → "Members and roles", and
// from the "Manage family members" link below) — this page only ever reads
// Home-scoped data, never writes it.

// No presence/location capability exists anywhere in the product today
// (checked: Member carries no status/presence field, and the backend has
// no such concept — see the task's own investigation requirement). Rather
// than inventing one, or inferring physical location from anything
// sensitive, the status row falls back to each member's real household
// relationship — an honest, stable fact about them, never a fabricated
// "Home"/"Away"/"Work" guess. There is deliberately no presence dot next
// to the avatar either: even a neutral colour reads as an implied
// online/location indicator, which would misrepresent what the app
// actually knows.
const relationshipStatusLabel: Record<HouseholdRelationship, string> = {
  home_admin: "Home Admin",
  partner: "Partner",
  adult: "Adult",
  child: "Child",
  extended_family: "Extended Family",
  friend: "Friend",
  review_required: "Member",
};

// Chat is not implemented yet — see the Family redesign task's explicit
// "framework only" scope. A narrowly-scoped UI flag (not a backend
// FeatureKey: there is no chat backend for one to gate), default off, no
// APIs, no storage, no migrations. Flip this — and start passing real
// `messages`/`unreadCount` into FamilyChatPreview — once a properly
// security-reviewed chat implementation exists.
const FAMILY_CHAT_ENABLED = false;

function eventTimeLabel(value: string, timezone: string, isAllDay: boolean): string {
  if (isAllDay) return "All day";
  return new Intl.DateTimeFormat("en-GB", { timeStyle: "short", timeZone: timezone }).format(
    new Date(value),
  );
}

function minutesOfDay(value: string, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).formatToParts(new Date(value));
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? "0");
  return hour * 60 + minute;
}

function minutesFromClock(value: string): number {
  const [hour, minute] = value.split(":");
  return Number(hour ?? 0) * 60 + Number(minute ?? 0);
}

const MEAL_SLOT_MINUTES: Record<string, number> = { breakfast: 8 * 60, lunch: 12 * 60, dinner: 18 * 60 };
const MEAL_SLOT_LABEL: Record<string, string> = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner" };

function mealEntryTitle(entry: MealPlanEntry): string {
  return entry.meal_name ?? entry.quick_meal_name ?? "Meal";
}

function addDaysIso(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// One row in "Today with the family" — a Home-shared representation of
// four otherwise-separate domains (calendar, routines, reminders, meals).
// Composed entirely client-side from data the page already needs to load
// for other reasons; see the completion report for why a dedicated backend
// endpoint isn't warranted for a capped, 4-row household glance.
interface FeedRow {
  key: string;
  avatarMember: Member | null;
  title: string;
  timeLabel: string;
  sortMinutes: number;
  href: string | null;
}

function FamilyAvatar({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const px = { sm: 32, md: 44, lg: 56 }[size];
  return (
    <span
      className={`avatar avatar-${size} family-generic-avatar`}
      style={{ width: px, height: px }}
      aria-hidden="true"
    >
      <Users size={Math.round(px * 0.45)} />
    </span>
  );
}

function FeedRowAvatar({ member }: { member: Member | null }) {
  if (!member) return <FamilyAvatar size="sm" />;
  return (
    <Avatar
      id={member.user_id}
      name={member.display_name}
      colour={member.colour}
      avatarVersion={member.avatar_version}
      size="sm"
    />
  );
}

export default function Family() {
  const { activeHome, activeHomeId } = useActiveHome();
  const [members, setMembers] = useState<Member[]>([]);
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [mealsToday, setMealsToday] = useState<MealPlanEntry[]>([]);
  const [weekEventCount, setWeekEventCount] = useState<number | null>(null);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    let cancelled = false;
    api
      .members(activeHomeId)
      .then((rows) => {
        if (!cancelled) setMembers(rows);
      })
      .catch((cause: Error) => !cancelled && setError(cause.message));
    return () => {
      cancelled = true;
    };
  }, [activeHomeId]);

  useEffect(() => {
    if (!activeHomeId) return;
    let cancelled = false;
    // Each source degrades independently — a Child with no calendar
    // visibility, or a Home with Meal Plans/Routines/Reminders not
    // released, still gets a correct (just smaller) overview rather than
    // one failure blanking the whole page. Mirrors Home's own pattern for
    // exactly the same reason.
    api
      .homeSummary(activeHomeId)
      .then((value) => !cancelled && setSummary(value))
      .catch(() => !cancelled && setSummary(null));
    api
      .routines(activeHomeId, { home: true })
      .then((response) => !cancelled && setRoutines(response.items))
      .catch(() => !cancelled && setRoutines([]));
    api
      .reminders(activeHomeId, { home: true })
      .then((response) => !cancelled && setReminders(response.items))
      .catch(() => !cancelled && setReminders([]));
    api
      .billingStatus(activeHomeId)
      .then(async (billing) => {
        if (!billing.meals_enabled || cancelled) return;
        const day = await api.mealPlanDay(activeHomeId, localIsoDate());
        if (!cancelled) setMealsToday(day.entries);
      })
      .catch(() => undefined);
    api
      .birthdays(activeHomeId)
      .then((response) => !cancelled && setBirthdays(response.items))
      .catch(() => !cancelled && setBirthdays([]));
    // "Family events" (Our week) deliberately counts only this Home's own
    // calendar via listEvents — it does NOT include events from calendars
    // externally shared into this Home. Home's own upcoming-events card
    // aggregates Home + every shared calendar (see fetchUpcomingCandidates
    // in app/home/page.tsx), but that's an N+1 fan-out over api.sharedCalendars()
    // built for a 3-item "next up" list, not a simple reusable selector —
    // reusing it here for a single weekly count would add a non-trivial
    // amount of fetching for a stat tile. Left as follow-up work rather than
    // pulled in during this polish pass; see the completion report.
    const today = localIsoDate();
    api
      .listEvents(activeHomeId, {
        start_at: `${today}T00:00:00Z`,
        end_at: `${addDaysIso(today, 7)}T00:00:00Z`,
      })
      .then((response) => !cancelled && setWeekEventCount(response.items.length))
      .catch(() => !cancelled && setWeekEventCount(null));
    return () => {
      cancelled = true;
    };
  }, [activeHomeId]);

  const memberById = useMemo(() => new Map(members.map((member) => [member.user_id, member])), [members]);

  const openRoutines = useMemo(() => routines.filter((routine) => !routine.home_completed_at), [routines]);
  const openReminders = useMemo(() => reminders.filter((reminder) => !reminder.home_completed_at), [reminders]);
  const upcomingBirthdays = useMemo(
    () => birthdays.filter((entry) => isBirthdayThisMonthAndUpcoming(entry)),
    [birthdays],
  );

  const feedRows: FeedRow[] = useMemo(() => {
    const rows: FeedRow[] = [];
    for (const event of summary?.today_events ?? []) {
      const participants = participantsForEvent(members, event.member_ids);
      rows.push({
        key: `event:${event.occurrence_id}`,
        avatarMember: participants.length === 1 ? (participants[0] ?? null) : null,
        title: event.title,
        timeLabel: eventTimeLabel(event.start_at, event.timezone, event.is_all_day),
        sortMinutes: event.is_all_day ? 0 : minutesOfDay(event.start_at, event.timezone),
        href: "/calendar",
      });
    }
    for (const routine of openRoutines) {
      const owner = routine.scope === "personal" ? (memberById.get(routine.owner_user_id ?? "") ?? null) : null;
      rows.push({
        key: `routine:${routine.id}`,
        avatarMember: owner,
        title: routine.title,
        timeLabel: routineDueLabel(routine.home_occurrence_date),
        sortMinutes: 22 * 60,
        href: "/settings/routines-reminders",
      });
    }
    for (const reminder of openReminders) {
      const owner = reminder.scope === "personal" ? (memberById.get(reminder.owner_user_id ?? "") ?? null) : null;
      rows.push({
        key: `reminder:${reminder.id}`,
        avatarMember: owner,
        title: reminder.title,
        timeLabel: routineDueLabel(reminder.home_occurrence_date),
        sortMinutes: minutesFromClock(reminder.due_time),
        href: "/settings/routines-reminders",
      });
    }
    for (const entry of mealsToday) {
      rows.push({
        key: `meal:${entry.id}`,
        avatarMember: null,
        title: mealEntryTitle(entry),
        timeLabel: MEAL_SLOT_LABEL[entry.meal_slot] ?? "Meal",
        sortMinutes: entry.time ? minutesFromClock(entry.time) : (MEAL_SLOT_MINUTES[entry.meal_slot] ?? 12 * 60),
        href: "/meal-plans",
      });
    }
    return rows.sort((a, b) => a.sortMinutes - b.sortMinutes).slice(0, 4);
  }, [summary, openRoutines, openReminders, mealsToday, members, memberById]);

  const routinesLeftCount = openRoutines.length;
  const remindersDueCount = openReminders.length;

  return (
    <AppShellContent>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{(activeHome?.name ?? "Your Home").toUpperCase()}</p>
            <h1>Family</h1>
            <p className="muted">What&rsquo;s happening with your people</p>
          </div>
        </div>

        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        <div className="family-status-row" role="list" aria-label="Household members">
          {members.map((member) => (
            <div className="family-status-item" role="listitem" key={member.user_id}>
              <Avatar
                id={member.user_id}
                name={member.display_name}
                colour={member.colour}
                avatarVersion={member.avatar_version}
                size="lg"
              />
              <span className="family-status-name">{member.display_name}</span>
              <span className="family-status-label">{relationshipStatusLabel[member.relationship]}</span>
            </div>
          ))}
        </div>

        <FamilyChatPreview enabled={FAMILY_CHAT_ENABLED} />

        <section className="card family-feed-card">
          <div className="section-heading">
            <div>
              <h2>Today with the family</h2>
              <p className="muted">Here&rsquo;s what&rsquo;s coming up</p>
            </div>
          </div>
          {feedRows.length === 0 ? (
            <p className="empty-mini">Nothing on today — enjoy the quiet.</p>
          ) : (
            <div className="family-feed-list">
              {feedRows.map((row) =>
                row.href ? (
                  <Link className="family-feed-row" href={row.href} key={row.key}>
                    <FeedRowAvatar member={row.avatarMember} />
                    <span className="family-feed-copy">
                      <strong>{row.avatarMember?.display_name ?? "Family"}</strong>
                      <span>{row.title}</span>
                    </span>
                    <span className="family-feed-time">{row.timeLabel}</span>
                    <ChevronRight size={16} className="family-feed-chevron" aria-hidden="true" />
                  </Link>
                ) : (
                  <div className="family-feed-row" key={row.key}>
                    <FeedRowAvatar member={row.avatarMember} />
                    <span className="family-feed-copy">
                      <strong>{row.avatarMember?.display_name ?? "Family"}</strong>
                      <span>{row.title}</span>
                    </span>
                    <span className="family-feed-time">{row.timeLabel}</span>
                  </div>
                ),
              )}
            </div>
          )}
        </section>

        <section className="card family-stats-card">
          <div className="section-heading">
            <div>
              <h2>Our week</h2>
              <p className="muted">A quick overview</p>
            </div>
          </div>
          <div className="family-stats-grid">
            <div className="family-stat-tile">
              <strong>{weekEventCount ?? "—"}</strong>
              <span>Family events</span>
            </div>
            <div className="family-stat-tile">
              <strong>{routinesLeftCount}</strong>
              <span>Routines left</span>
            </div>
            <div className="family-stat-tile">
              <strong>{remindersDueCount}</strong>
              <span>Reminders due</span>
            </div>
            <div className="family-stat-tile family-stat-tile-text">
              <strong>
                {upcomingBirthdays.length === 0
                  ? "No birthdays"
                  : `${upcomingBirthdays.length} birthday${upcomingBirthdays.length === 1 ? "" : "s"}`}
              </strong>
              <span>This month</span>
            </div>
          </div>
        </section>

        <Link className="family-manage-link" href="/settings/members">
          Manage family members
          <ChevronRight size={18} aria-hidden="true" />
        </Link>

        {members.length > 0 && (
          <section aria-labelledby="family-everyone-title">
            <div className="section-heading">
              <h2 id="family-everyone-title">Everyone</h2>
            </div>
            <div className="family-everyone-grid">
              {members.map((member) => {
                const eventsToday = (summary?.today_events ?? []).filter((event) =>
                  event.member_ids.includes(member.user_id),
                ).length;
                const remindersForMember = openReminders.filter(
                  (reminder) => reminder.owner_user_id === member.user_id,
                ).length;
                return (
                  <Link
                    className="card family-everyone-card"
                    href="/settings/members"
                    key={member.user_id}
                  >
                    <Avatar
                      id={member.user_id}
                      name={member.display_name}
                      colour={member.colour}
                      avatarVersion={member.avatar_version}
                      size="lg"
                    />
                    <span className="family-everyone-name">
                      <strong>{member.display_name}</strong>
                      <span className="role-badge">{relationshipStatusLabel[member.relationship]}</span>
                    </span>
                    <span className="family-everyone-summary">
                      {eventsToday} event{eventsToday === 1 ? "" : "s"} · {remindersForMember} reminder
                      {remindersForMember === 1 ? "" : "s"}
                    </span>
                    <span className="family-everyone-view">
                      Manage member
                      <ChevronRight size={14} aria-hidden="true" />
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}
      </main>
    </AppShellContent>
  );
}
