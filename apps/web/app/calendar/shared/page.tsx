"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { CalendarShare } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

// "Shared with me" — calendars other Homes have shared with the signed-in
// user (see apps/api/mykhaya/routers/calendar_sharing.py's shared_router).
// Deliberately its own page, top-level under /calendar rather than
// home-scoped: a share recipient may belong to a different Home than the
// one sharing with them, or (a brand-new Free signup) to none at all.
export default function SharedCalendarsPage() {
  // Enabled unconditionally (unlike other pages) — a Home-less Free
  // recipient is exactly who this page must keep working for (see
  // AppShell's onboarding-redirect exemption for this path).
  const { homes, loading: homesLoading } = useActiveHome();
  const [items, setItems] = useState<CalendarShare[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api.sharedCalendars();
      setItems(result.items);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load shared calendars.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function updatePreferences(
    share: CalendarShare,
    changes: { notification_preference?: "all" | "important" | "off"; include_in_briefing?: boolean },
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api.updateCalendarSharePreferences(share.id, changes);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save that setting.");
    } finally {
      setBusy(false);
    }
  }

  async function leave(share: CalendarShare) {
    if (busy) return;
    if (
      !window.confirm(
        `Stop seeing "${share.calendar_name}"? You can be re-invited later if you change your mind.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.leaveCalendarShare(share.id);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not leave that calendar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShellContent>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Calendar</p>
            <h1>Shared with me</h1>
            <p className="muted">
              Calendars other households have shared with you — they sit
              alongside your own, clearly marked as shared.
            </p>
          </div>
        </div>

        <FormStatus error={error} />

        {/* Gentle, optional — never blocking: a Free recipient's whole
            reason for being here is to use what's already been shared with
            them, not to be sold Family. See docs on external Calendar
            Sharing, "Home-less Free account UX"/"Growth opportunity". */}
        {!homesLoading && homes.length === 0 && (
          <p className="quiet-state calendar-shared-home-cta">
            Using MyKhaya without your own Home for now?{" "}
            <Link href="/onboarding">Create your own Home</Link> whenever you're ready.
          </p>
        )}

        {!loaded ? (
          <p role="status">Loading shared calendars…</p>
        ) : items.length === 0 ? (
          <p className="quiet-state">
            No one has shared a calendar with you yet. When they do, it will appear here.
          </p>
        ) : (
          <div className="settings-list">
            {items.map((share) => (
              <div className="card" key={share.id}>
                <div className="calendar-sharing-panel">
                  <div>
                    <h2>{share.calendar_name}</h2>
                    <p className="quiet-state">
                      Shared by {share.source_group_name} ·{" "}
                      {share.permission === "manage" ? "Can add & edit" : "Can view"}
                    </p>
                  </div>
                  <label>
                    Notifications
                    <select
                      value={share.notification_preference}
                      disabled={busy}
                      onChange={(event) =>
                        updatePreferences(share, {
                          notification_preference: event.target.value as
                            | "all"
                            | "important"
                            | "off",
                        })
                      }
                    >
                      <option value="all">All activity</option>
                      <option value="important">Important changes only</option>
                      <option value="off">Off</option>
                    </select>
                  </label>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={share.include_in_briefing}
                      disabled={busy}
                      onChange={(event) =>
                        updatePreferences(share, { include_in_briefing: event.target.checked })
                      }
                    />
                    Include in my morning briefing
                  </label>
                  <div className="actions compact-actions">
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => leave(share)}
                    >
                      Leave
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </AppShellContent>
  );
}
