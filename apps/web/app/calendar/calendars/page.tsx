"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { HomeCalendar } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import {
  atLimitMessage,
  calendarBadgeLabel,
  canCreateCalendar,
} from "@/components/calendar-entitlement-logic";

// Calendar management (Phase 6) — deliberately its own small page rather
// than woven into the month/week/day/agenda calendar view, so the existing
// event views stay entirely untouched (they already show every calendar's
// events together via the Home-scoped event list; see
// docs/architecture/commercial-entitlements.md#calendar-as-proof-of-architecture
// for why no per-view filtering was needed).
export default function CalendarsPage() {
  const { activeHomeId, loading: homeLoading } = useActiveHome();
  const [items, setItems] = useState<HomeCalendar[]>([]);
  const [limit, setLimit] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    if (!activeHomeId) return;
    try {
      const result = await api.listCalendars(activeHomeId);
      setItems(result.items);
      setLimit(result.limit);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load calendars.");
    } finally {
      setLoaded(true);
    }
  }, [activeHomeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const usage = { count: items.length, limit, over_limit: limit !== null && items.length > limit };
  const atLimit = atLimitMessage(usage);

  async function createCalendar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || busy || !newName.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.createCalendar(activeHomeId, { name: newName.trim() });
      setNewName("");
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not create that calendar.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteCalendar(calendarId: string) {
    if (!activeHomeId || busy) return;
    if (!window.confirm("Delete this calendar? Its events are deleted too — this can't be undone.")) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.deleteCalendar(activeHomeId, calendarId, { confirmed: true });
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete that calendar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Calendar</p>
            <h1>Calendars</h1>
          </div>
        </div>

        <FormStatus error={error} />

        {!loaded || homeLoading ? (
          <p role="status">Loading calendars…</p>
        ) : (
          <>
            <div className="settings-list">
              {items.map((calendar) => {
                const badge = calendarBadgeLabel(calendar);
                return (
                  <div className="card" key={calendar.id}>
                    <div>
                      <h2>
                        {calendar.name}
                        {calendar.is_primary ? " · Primary" : ""}
                      </h2>
                      {badge && (
                        <p className="quiet-state">
                          {badge} — events here can be viewed but not created, edited or deleted.
                        </p>
                      )}
                    </div>
                    {!calendar.is_primary && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() => deleteCalendar(calendar.id)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            <section className="card details">
              <h2>Add a calendar</h2>
              {canCreateCalendar(usage) ? (
                <form onSubmit={createCalendar}>
                  <label>
                    Calendar name
                    <input
                      value={newName}
                      onChange={(event) => setNewName(event.target.value)}
                      maxLength={80}
                      required
                    />
                  </label>
                  <button disabled={busy}>{busy ? "Adding…" : "Add calendar"}</button>
                </form>
              ) : (
                <>
                  <p>Multiple calendars are included with MyKhaya Family.</p>
                  {atLimit && <p className="quiet-state">{atLimit}</p>}
                  <Link className="button secondary" href="/settings/billing">
                    Upgrade to Family
                  </Link>
                </>
              )}
            </section>
          </>
        )}
      </main>
    </AppShell>
  );
}
