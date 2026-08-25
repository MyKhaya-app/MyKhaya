"use client";

import Link from "next/link";
import { Children, useEffect, useState } from "react";
import {
  Bell,
  CalendarPlus,
  Check,
  ClipboardList,
  Gift,
  ListChecks,
  Lock,
  UserPlus,
  UtensilsCrossed,
} from "lucide-react";
import type {
  BirthdayEntry,
  EventOccurrence,
  HomeSummary,
  Member,
  Routine,
  User,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar, AvatarStack, memberColour } from "@/components/avatar";
import { participantsForEvent } from "@/components/avatar-stack-logic";
import { isStandalone } from "@/components/install-prompt";
import { canAddMember } from "@/components/member-entitlement-logic";
import { MealPlansTodayCard } from "@/components/meal-plans-today-card";
import { subscribeToPush } from "@/components/push-subscribe";
import { useActiveHome } from "@/components/use-active-home";
import {
  birthdayDateLabel,
  daysUntilThisYear,
  isBirthdayThisMonthAndUpcoming,
  upcomingBirthdayIcon,
  upcomingBirthdayLabel,
} from "./birthday-utils";
import { routineDueLabel } from "./routine-utils";
import {
  eventDateBounds,
  eventOnOrAfterDate,
  tomorrowDateKey,
} from "../calendar/calendar-utils";

function eventTime(value: string, timezone: string) {
  return new Intl.DateTimeFormat("en-GB", {
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

function eventDateStack(value: string, timezone: string) {
  const date = new Date(value);
  return {
    weekday: new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: timezone }).format(date),
    day: new Intl.DateTimeFormat("en-GB", { day: "numeric", timeZone: timezone }).format(date),
    month: new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: timezone }).format(date),
  };
}

function isComingUp(event: EventOccurrence): boolean {
  const timeZone = event.timezone;
  return eventOnOrAfterDate(event, timeZone, tomorrowDateKey(timeZone));
}

// The backend answers "next N occurrences on/after a cursor" per source
// (Home + each externally shared calendar) with no future-date horizon —
// see calendar_occurrences.upcoming_candidate_filter/next_occurrence_on_or_after.
// The cursor here is a generous 24h-back UTC buffer (comfortably more than
// any real UTC offset) so a boundary occurrence is never missed before the
// exact, timezone-correct isComingUp/compareUpcoming pass below narrows it
// down to the real "after today" set; UPCOMING_FETCH_LIMIT similarly asks
// for more than the 3 ultimately shown so that pass always has enough to
// choose from.
const UPCOMING_FETCH_LIMIT = 8;

async function fetchUpcomingCandidates(homeId: string): Promise<EventOccurrence[]> {
  const after = new Date(Date.now() - 86_400_000).toISOString();
  const [homeUpcoming, shares] = await Promise.all([
    api.listUpcomingEvents(homeId, { after, limit: UPCOMING_FETCH_LIMIT }),
    api.sharedCalendars().catch(() => ({ items: [] })),
  ]);
  const sharedUpcomingLists = await Promise.all(
    shares.items.map((share) =>
      api
        .listUpcomingSharedEvents(share.id, { after, limit: UPCOMING_FETCH_LIMIT })
        .then((response) =>
          response.items.map(
            (item): EventOccurrence => ({
              ...item,
              share_id: share.id,
              share_permission: share.permission,
              shared_by_home_name: share.source_group_name,
            }),
          ),
        )
        .catch(() => []),
    ),
  );
  return [...homeUpcoming.items, ...sharedUpcomingLists.flat()];
}

function compareUpcoming(left: EventOccurrence, right: EventOccurrence): number {
  const leftBounds = eventDateBounds(left, left.timezone);
  const rightBounds = eventDateBounds(right, right.timezone);
  return (
    leftBounds.startKey.localeCompare(rightBounds.startKey) ||
    Number(right.is_all_day) - Number(left.is_all_day) ||
    left.start_at.localeCompare(right.start_at) ||
    left.title.localeCompare(right.title) ||
    left.occurrence_id.localeCompare(right.occurrence_id)
  );
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// An empty day is good news, not a report of zero rows — rotated so the
// app doesn't repeat itself. Stable within a day rather than re-randomised
// on every render. See docs/design/visual-identity.md.
const TODAY_EMPTY_STATES = [
  { icon: "🌿", text: "Your day's looking nice and calm." },
  { icon: "✨", text: "Nothing planned just yet." },
  { icon: "☀️", text: "Enjoy the quieter day." },
];
function todayEmptyState() {
  const dayOfYear = Math.floor(
    (Date.now() - new Date(new Date().getFullYear(), 0, 0).getTime()) / 86_400_000,
  );
  return TODAY_EMPTY_STATES[dayOfYear % TODAY_EMPTY_STATES.length]!;
}

function notificationsSupported() {
  return typeof window !== "undefined" && "Notification" in window;
}

// Warm, family-organiser phrasing rather than a system-generated alert — rotated by
// day of year so it's stable within a day but varies day to day, matching
// TODAY_EMPTY_STATES below. See docs/design/visual-identity.md.
const BIRTHDAY_TODAY_PHRASES = [
  (name: string) => `🎉 Today we're celebrating ${name}.`,
  (name: string) => `🎂 Don't forget… it's ${name}'s birthday today.`,
  (name: string) => `🎈 Today's a special day. It's ${name}'s birthday.`,
];

function dayOfYear() {
  return Math.floor(
    (Date.now() - new Date(new Date().getFullYear(), 0, 0).getTime()) / 86_400_000,
  );
}

function birthdayTodayPhrase(name: string) {
  return BIRTHDAY_TODAY_PHRASES[dayOfYear() % BIRTHDAY_TODAY_PHRASES.length]!(name);
}


function EventRow({
  event,
  members,
  leading,
}: {
  event: EventOccurrence;
  members: Member[];
  leading: React.ReactNode;
}) {
  const [firstMember] = members;
  return (
    <Link className="home-event-row" href="/calendar">
      <span
        className="home-event-colour"
        style={{
          background: firstMember
            ? memberColour(firstMember.user_id, firstMember.colour)
            : "var(--colour-sage)",
        }}
        aria-hidden="true"
      />
      <span className="home-event-leading">{leading}</span>
      <span className="home-event-copy">
        <strong>{event.title}</strong>
        {event.location_text && <small>{event.location_text}</small>}
      </span>
      {members.length > 0 ? (
        <AvatarStack people={members} size="sm" />
      ) : (
        <span className="home-event-avatar-placeholder" aria-hidden="true" />
      )}
    </Link>
  );
}

// A row within "Around the house" that sizes its own columns to however
// many shortcuts actually render into it (children are conditional on
// entitlements/feature flags) — so a row never shows a blank placeholder
// tile, and adding/removing a shortcut from either row doesn't require any
// layout math elsewhere. Generic over the number of shortcuts, not tied to
// any specific one.
function QuickActionsRow({ children }: { children: React.ReactNode }) {
  const items = Children.toArray(children).filter(Boolean);
  if (items.length === 0) return null;
  return <div className={`quick-actions-row quick-actions-row-${items.length}`}>{items}</div>;
}

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [upcoming, setUpcoming] = useState<EventOccurrence[]>([]);
  const [calendarEnabled, setCalendarEnabled] = useState(false);
  const [mealsFeatureOn, setMealsFeatureOn] = useState(false);
  const [mealsEnabled, setMealsEnabled] = useState(false);
  const [listsFeatureOn, setListsFeatureOn] = useState(false);
  const [listsEnabled, setListsEnabled] = useState(false);
  const [wishlistsFeatureOn, setWishlistsFeatureOn] = useState(false);
  const [wishlistsEnabled, setWishlistsEnabled] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [routinesExpanded, setRoutinesExpanded] = useState(false);
  const [canInviteMore, setCanInviteMore] = useState(false);
  const [error, setError] = useState("");
  const [notifPermission, setNotifPermission] = useState<NotificationPermission | null>(null);
  const { activeHomeId, activeHome } = useActiveHome();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
    if (notificationsSupported()) setNotifPermission(Notification.permission);
  }, []);

  useEffect(() => {
    if (!activeHomeId) return;
    setError("");
    api
      .birthdays(activeHomeId)
      .then((response) => setBirthdays(response.items))
      .catch(() => setBirthdays([]));
    api
      .billingStatus(activeHomeId)
      .then((billing) => {
        setCanInviteMore(canAddMember(billing.member_usage));
        setMealsEnabled(billing.meals_enabled);
        setListsEnabled(billing.lists_enabled);
        setWishlistsEnabled(billing.wishlists_enabled);
      })
      .catch(() => {
        setCanInviteMore(false);
        setMealsEnabled(false);
        setListsEnabled(false);
        setWishlistsEnabled(false);
      });
    Promise.all([api.featureMatrix(activeHomeId), api.members(activeHomeId)])
      .then(async ([matrix, memberRows]) => {
        setMembers(memberRows);
        const enabled = matrix.features.some(
          (feature) => feature.feature === "calendar" && feature.enabled,
        );
        setCalendarEnabled(enabled);
        setMealsFeatureOn(
          matrix.features.some((feature) => feature.feature === "meals" && feature.enabled),
        );
        setListsFeatureOn(
          matrix.features.some((feature) => feature.feature === "shopping" && feature.enabled),
        );
        setWishlistsFeatureOn(
          matrix.features.some((feature) => feature.feature === "wish_lists" && feature.enabled),
        );
        const notificationsEnabled = matrix.features.some(
          (feature) => feature.feature === "notifications" && feature.enabled,
        );
        if (!enabled && !notificationsEnabled) {
          setSummary(null);
          setUpcoming([]);
          setRoutines([]);
          return;
        }
        const [calendarData, routineData] = await Promise.all([
          enabled
            ? Promise.all([
                api.homeSummary(activeHomeId),
                fetchUpcomingCandidates(activeHomeId),
              ])
            : null,
          notificationsEnabled ? api.routines(activeHomeId, { home: true }) : null,
        ]);
        if (calendarData) {
          const [homeSummary, upcomingRows] = calendarData;
          setSummary(homeSummary);
          const todayOccurrenceIds = new Set(
            homeSummary.today_events.map((event) => event.occurrence_id),
          );
          setUpcoming(
            upcomingRows
              .filter(
                (event) =>
                  !todayOccurrenceIds.has(event.occurrence_id) && isComingUp(event),
              )
              .sort(compareUpcoming)
              .slice(0, 3),
          );
        } else {
          setSummary(null);
          setUpcoming([]);
        }
        setRoutines(routineData?.items ?? []);
        setRoutinesExpanded(false);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [activeHomeId]);

  // Reuses GET /groups/{id}/members' existing display_name ordering (members
  // is already fetched once, in that order, for the whole Home) rather than
  // inventing a new order — same list, just filtered per event, so it's
  // always deterministic and never depends on event.member_ids' own order.
  function membersForEvent(memberIds: string[]) {
    return participantsForEvent(members, memberIds);
  }

  async function enableNotifications() {
    if (!notificationsSupported()) return;
    const result = await subscribeToPush();
    setNotifPermission(typeof Notification !== "undefined" ? Notification.permission : null);
    if (!result.ok && result.reason === "error") {
      setError("Could not enable notifications on this device. Please try again.");
    }
  }

  async function completeRoutine(routine: Routine) {
    if (!activeHomeId || !routine.home_occurrence_date || routine.home_completed_at) return;
    const previous = routines;
    const completedAt = new Date().toISOString();
    setRoutines((current) =>
      current.map((item) =>
        item.id === routine.id
          ? {
              ...item,
              home_completed_at: completedAt,
              home_completed_by_user_id: user?.id ?? null,
              home_completed_by_display_name: user?.display_name ?? "You",
            }
          : item,
      ),
    );
    try {
      await api.completeRoutine(activeHomeId, routine.id, routine.home_occurrence_date);
    } catch (cause) {
      setRoutines(previous);
      setError((cause as Error).message);
    }
  }

  // Requesting push permission before the app is installed leads nowhere useful on
  // iOS Safari (Notification.requestPermission works, but there is no way to receive
  // push while the tab is closed) — so the prompt only appears once installed.
  const showNotificationPrompt =
    notificationsSupported() && notifPermission === "default" && isStandalone();
  const showInstallFirstNotice =
    notificationsSupported() && notifPermission === "default" && !isStandalone();
  const emptyState = todayEmptyState();
  // The API's home=true view already returns routines in Home's exact
  // priority order (overdue, due today, upcoming, then completed) — see
  // household_routines.list_routines — so this only slices for the
  // show-more/show-less toggle, it doesn't re-sort.
  const visibleRoutines = routinesExpanded ? routines : routines.slice(0, 3);

  return (
    <AppShell
      hero={
        <div className="home-hero">
          <p className="home-hero-eyebrow">🌿 {greeting()},</p>
          <h1>{user?.display_name?.split(" ")[0] ?? "there"}</h1>
          <p>
            {activeHome
              ? `Here's what's happening in your home`
              : "Select a Home to continue"}
          </p>
          {members.length > 0 && (
            <div className="home-family-strip" aria-label="Your family">
              {members.map((member) => (
                <Avatar
                  key={member.user_id}
                  id={member.user_id}
                  name={member.display_name}
                  colour={member.colour}
                  avatarVersion={member.avatar_version}
                  size="md"
                />
              ))}
            </div>
          )}
        </div>
      }
    >
      <main className="home-page">
        {error && <p className="notice error">{error}</p>}

        {(() => {
          const thisMonthBirthdays = birthdays.filter((entry) => isBirthdayThisMonthAndUpcoming(entry));
          if (!thisMonthBirthdays.length) return null;
          return (
            <section className="card home-section birthday-banner">
              <div className="section-heading">
                <h2>
                  <Gift size={18} aria-hidden="true" /> Birthdays this month
                </h2>
              </div>
              <div className="birthday-list">
                {thisMonthBirthdays.slice(0, 5).map((entry) => {
                  const days = daysUntilThisYear(entry);
                  return (
                    <div className="birthday-row" key={`${entry.owner_type}:${entry.owner_id}`}>
                      <span className="birthday-row-icon" aria-hidden="true">
                        {upcomingBirthdayIcon(days)}
                      </span>
                      <span className="birthday-row-copy">
                        <strong>
                          {days === 0 ? birthdayTodayPhrase(entry.display_name) : entry.display_name}
                        </strong>
                        <small>
                          {birthdayDateLabel(entry)}
                          {days !== 0 && ` · ${upcomingBirthdayLabel(days)}`}
                        </small>
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })()}

        {calendarEnabled && (
          <section className="card home-section home-section-overlap">
            <div className="section-heading">
              <h2>Today</h2>
              <Link className="tertiary" href="/calendar">
                See all
              </Link>
            </div>
            {!summary?.today_events?.length ? (
              <div className="home-empty-state">
                <p>
                  {emptyState.icon} {emptyState.text}
                </p>
                <Link className="tertiary" href="/calendar">
                  <CalendarPlus size={16} aria-hidden="true" />
                  Add an event
                </Link>
              </div>
            ) : (
              <div className="home-event-list">
                {summary.today_events.map((event) => (
                  <EventRow
                    key={event.occurrence_id}
                    event={event}
                    members={membersForEvent(event.member_ids)}
                    leading={eventTime(event.start_at, event.timezone)}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {routines.length > 0 && (
          <section className="card home-section home-todo-section">
            <div className="section-heading">
              <h2>To do</h2>
              <Link className="tertiary" href="/settings/routines">
                See all
              </Link>
            </div>
            <div className="home-routine-list" id="home-routine-list">
              {visibleRoutines.map((routine) => {
                const completed = Boolean(routine.home_completed_at);
                return (
                  <div className={`home-routine-row${completed ? " is-complete" : ""}`} key={routine.id}>
                    <button
                      className="home-routine-check"
                      type="button"
                      aria-label={`${completed ? "Completed" : "Complete"} ${routine.title}`}
                      aria-pressed={completed}
                      onClick={() => completeRoutine(routine)}
                      disabled={completed}
                    >
                      <span className="home-routine-check-dot" aria-hidden="true">
                        {completed && <Check size={10} />}
                      </span>
                    </button>
                    <Link className="home-routine-copy" href="/settings/routines">
                      <strong>{routine.title}</strong>
                      <small>
                        {completed
                          ? routine.scope === "household" && routine.home_completed_by_display_name
                            ? `Done by ${routine.home_completed_by_display_name} · ${new Intl.DateTimeFormat("en-GB", { timeStyle: "short" }).format(new Date(routine.home_completed_at!))}`
                            : `Done · ${new Intl.DateTimeFormat("en-GB", { timeStyle: "short" }).format(new Date(routine.home_completed_at!))}`
                          : `${routineDueLabel(routine.home_occurrence_date)} · ${routine.scope === "household" ? "Household" : "Personal"}`}
                      </small>
                    </Link>
                  </div>
                );
              })}
            </div>
            {routines.length > 3 && (
              <button
                className="home-routine-expand tertiary"
                type="button"
                aria-expanded={routinesExpanded}
                aria-controls="home-routine-list"
                onClick={() => setRoutinesExpanded((expanded) => !expanded)}
              >
                {routinesExpanded ? "Show less" : "Show more"}
              </button>
            )}
          </section>
        )}

        {activeHomeId && <MealPlansTodayCard homeId={activeHomeId} />}

        {calendarEnabled && (
          <section className="card home-section">
            <div className="section-heading">
              <h2>Coming up</h2>
              <Link className="tertiary" href="/calendar">
                See all
              </Link>
            </div>
            {!upcoming.length ? (
              <p className="empty-mini">Nothing else planned yet.</p>
            ) : (
              <div className="home-event-list">
                {upcoming.map((event) => {
                  const stack = eventDateStack(event.start_at, event.timezone);
                  return (
                    <EventRow
                      key={event.occurrence_id}
                      event={event}
                      members={membersForEvent(event.member_ids)}
                      leading={
                        <span className="home-event-date-stack">
                          <strong>
                            {stack.weekday} {stack.day}
                          </strong>
                          <small>{stack.month}</small>
                        </span>
                      }
                    />
                  );
                })}
              </div>
            )}
          </section>
        )}

        <section className="card home-section">
          <div className="section-heading">
            <h2>Around the house</h2>
          </div>
          <div className="quick-actions">
            <QuickActionsRow>
              {calendarEnabled && (
                <Link className="quick-action" href="/calendar">
                  <CalendarPlus size={20} aria-hidden="true" />
                  Add event
                </Link>
              )}
              {canInviteMore && (
                <Link className="quick-action" href="/people">
                  <UserPlus size={20} aria-hidden="true" />
                  Invite family
                </Link>
              )}
            </QuickActionsRow>
            {/* Routines has no feature flag of its own — same as its More →
                Settings entry, the shortcut always links through to
                /settings/routines, which owns the personal-vs-household
                (Free vs Family) gating itself. */}
            <QuickActionsRow>
              <Link className="quick-action" href="/settings/routines">
                <ClipboardList size={20} aria-hidden="true" />
                Routines
              </Link>
              {mealsFeatureOn && (
                <Link
                  className={`quick-action${mealsEnabled ? "" : " quick-action-locked"}`}
                  href="/meal-plans"
                >
                  {!mealsEnabled && (
                    <span className="quick-action-lock" aria-hidden="true">
                      <Lock size={11} />
                    </span>
                  )}
                  <UtensilsCrossed size={20} aria-hidden="true" />
                  Meal plans
                </Link>
              )}
              {listsFeatureOn && (
                <Link
                  className={`quick-action${listsEnabled ? "" : " quick-action-locked"}`}
                  href="/lists"
                >
                  {!listsEnabled && (
                    <span className="quick-action-lock" aria-hidden="true">
                      <Lock size={11} />
                    </span>
                  )}
                  <ListChecks size={20} aria-hidden="true" />
                  Lists
                </Link>
              )}
              {wishlistsFeatureOn && (
                <Link
                  className={`quick-action${wishlistsEnabled ? "" : " quick-action-locked"}`}
                  href="/wish-lists"
                >
                  {!wishlistsEnabled && (
                    <span className="quick-action-lock" aria-hidden="true">
                      <Lock size={11} />
                    </span>
                  )}
                  <Gift size={20} aria-hidden="true" />
                  Wishlists
                </Link>
              )}
            </QuickActionsRow>
          </div>
        </section>

        {showNotificationPrompt && (
          <section className="card notify-panel">
            <span className="notify-icon" aria-hidden="true">
              <Bell size={20} />
            </span>
            <div className="notify-copy">
              <strong>Stay in sync</strong>
              <p>Enable notifications so you never miss what matters.</p>
            </div>
            <button type="button" className="secondary" onClick={enableNotifications}>
              Enable
            </button>
          </section>
        )}

        {showInstallFirstNotice && (
          <section className="card notify-panel">
            <span className="notify-icon" aria-hidden="true">
              <Bell size={20} />
            </span>
            <div className="notify-copy">
              <strong>Install MyKhaya first</strong>
              <p>Add MyKhaya to your Home Screen to enable notifications.</p>
            </div>
          </section>
        )}
      </main>
    </AppShell>
  );
}
