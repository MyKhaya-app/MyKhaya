"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bell, CalendarPlus, Gift, UserPlus } from "lucide-react";
import type {
  BirthdayEntry,
  EventOccurrence,
  HomeSummary,
  Member,
  User,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar, memberColour } from "@/components/avatar";
import { isStandalone } from "@/components/install-prompt";
import { subscribeToPush } from "@/components/push-subscribe";
import { useActiveHome } from "@/components/use-active-home";
import {
  birthdayDateLabel,
  daysUntilThisYear,
  isBirthdayThisMonthAndUpcoming,
  upcomingBirthdayIcon,
  upcomingBirthdayLabel,
} from "./birthday-utils";

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
  member,
  leading,
}: {
  event: EventOccurrence;
  member: Member | null;
  leading: React.ReactNode;
}) {
  return (
    <Link className="home-event-row" href="/calendar">
      <span
        className="home-event-colour"
        style={{
          background: member ? memberColour(member.user_id, member.colour) : "var(--colour-sage)",
        }}
        aria-hidden="true"
      />
      <span className="home-event-leading">{leading}</span>
      <span className="home-event-copy">
        <strong>{event.title}</strong>
        {event.location_text && <small>{event.location_text}</small>}
      </span>
      {member ? (
        <Avatar id={member.user_id} name={member.display_name} colour={member.colour} size="sm" />
      ) : (
        <span className="home-event-avatar-placeholder" aria-hidden="true" />
      )}
    </Link>
  );
}

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [upcoming, setUpcoming] = useState<EventOccurrence[]>([]);
  const [calendarEnabled, setCalendarEnabled] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
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
    Promise.all([api.featureMatrix(activeHomeId), api.members(activeHomeId)])
      .then(async ([matrix, memberRows]) => {
        setMembers(memberRows);
        const enabled = matrix.features.some(
          (feature) => feature.feature === "calendar" && feature.enabled,
        );
        setCalendarEnabled(enabled);
        if (!enabled) {
          setSummary(null);
          setUpcoming([]);
          return;
        }
        const [homeSummary, upcomingRows] = await Promise.all([
          api.homeSummary(activeHomeId),
          api.listEvents(activeHomeId, {
            start_at: new Date(new Date().setUTCHours(24, 0, 0, 0)).toISOString(),
            end_at: new Date(
              new Date().setUTCDate(new Date().getUTCDate() + 14),
            ).toISOString(),
            page_size: 3,
          }),
        ]);
        setSummary(homeSummary);
        setUpcoming(upcomingRows.items.slice(0, 3));
      })
      .catch((reason: Error) => setError(reason.message));
  }, [activeHomeId]);

  function firstMember(memberIds: string[]) {
    return members.find((member) => memberIds.includes(member.user_id)) ?? null;
  }

  async function enableNotifications() {
    if (!notificationsSupported()) return;
    const result = await subscribeToPush();
    setNotifPermission(typeof Notification !== "undefined" ? Notification.permission : null);
    if (!result.ok && result.reason === "error") {
      setError("Could not enable notifications on this device. Please try again.");
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
                    member={firstMember(event.member_ids)}
                    leading={eventTime(event.start_at, event.timezone)}
                  />
                ))}
              </div>
            )}
          </section>
        )}

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
                      member={firstMember(event.member_ids)}
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
            {calendarEnabled && (
              <Link className="quick-action" href="/calendar">
                <CalendarPlus size={20} aria-hidden="true" />
                Add event
              </Link>
            )}
            <Link className="quick-action" href="/people">
              <UserPlus size={20} aria-hidden="true" />
              Invite family
            </Link>
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
