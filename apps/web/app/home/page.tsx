"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { HomeSummary, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { useActiveHome } from "@/components/use-active-home";

function eventTime(value: string, timezone: string) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [calendarEnabled, setCalendarEnabled] = useState(false);
  const [memberCount, setMemberCount] = useState(0);
  const [error, setError] = useState("");
  const { activeHomeId, activeHome } = useActiveHome();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (!activeHomeId) return;
    setError("");
    Promise.all([api.featureMatrix(activeHomeId), api.members(activeHomeId)])
      .then(async ([matrix, members]) => {
        setMemberCount(members.length);
        const enabled = matrix.features.some(
          (feature) => feature.feature === "calendar" && feature.enabled,
        );
        setCalendarEnabled(enabled);
        setSummary(enabled ? await api.homeSummary(activeHomeId) : null);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [activeHomeId]);

  return (
    <AppShell>
      <main className="home-page">
        <div className="page-intro">
          <p>Good day,</p>
          <h1>
            {user?.display_name ?? "there"} <span aria-hidden="true">👋</span>
          </h1>
          <small>
            {activeHome
              ? `Here is what is happening in ${activeHome.name}`
              : "Select a Home to continue"}
          </small>
        </div>

        {error && <p className="notice error">{error}</p>}

        <section className="home-grid">
          {calendarEnabled && (
            <article className="card details">
              <h2>Today in your Home</h2>
              {!summary?.today_events?.length ? (
                <p className="hint">
                  No events yet. Add your first family event to get started.
                </p>
              ) : (
                <div className="list-card">
                  {summary.today_events.map((event) => (
                    <article key={event.occurrence_id}>
                      <i aria-hidden="true">▣</i>
                      <div>
                        <strong>{event.title}</strong>
                        <small>
                          {eventTime(event.start_at, event.timezone)}
                        </small>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </article>
          )}

          <article className="card details">
            <h2>Overview</h2>
            <p>{summary?.member_count ?? memberCount} members in this Home</p>
            {summary && (
              <p>Pending invitations: {summary.pending_invitations ?? 0}</p>
            )}
            {calendarEnabled && summary?.next_event ? (
              <p>
                Next event: <strong>{summary.next_event.title}</strong>
                <br />
                <small>
                  {eventTime(
                    summary.next_event.start_at,
                    summary.next_event.timezone,
                  )}
                </small>
              </p>
            ) : calendarEnabled ? (
              <p className="hint">Nothing planned next yet.</p>
            ) : null}
            <div className="actions compact-actions">
              {calendarEnabled && (
                <Link className="button" href="/calendar">
                  Quick Add Event
                </Link>
              )}
              <Link className="button secondary" href="/people">
                Invite Family
              </Link>
            </div>
          </article>
        </section>
      </main>
    </AppShell>
  );
}
