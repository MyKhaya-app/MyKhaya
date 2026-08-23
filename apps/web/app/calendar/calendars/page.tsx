"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { CalendarShare, HomeCalendar } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import {
  atLimitMessage,
  calendarBadgeLabel,
  canCreateCalendar,
  canShareCalendar,
} from "@/components/calendar-entitlement-logic";

const shareStatusLabels: Record<CalendarShare["status"], string> = {
  pending_admin_approval: "Awaiting Home Admin approval",
  pending_recipient: "Invitation sent",
  accepted: "Active",
  declined: "Declined",
  revoked: "Revoked",
};

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
  const [sharePanel, setSharePanel] = useState<string | null>(null);
  const [shareEmail, setShareEmail] = useState("");
  const [sharePermission, setSharePermission] = useState<"view" | "manage">("view");
  const [shares, setShares] = useState<Record<string, CalendarShare[]>>({});
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState("");
  const [externalInvitesEnabled, setExternalInvitesEnabled] = useState(false);

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => setExternalInvitesEnabled(billing.external_invites_enabled))
      .catch(() => setExternalInvitesEnabled(false));
  }, [activeHomeId]);

  const load = useCallback(async () => {
    if (!activeHomeId) return;
    try {
      const result = await api.listCalendars(activeHomeId);
      setItems(result.items);
      setLimit(result.limit);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load event categories.");
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
      setError(cause instanceof ApiError ? cause.message : "Could not create that category.");
    } finally {
      setBusy(false);
    }
  }

  async function loadShares(calendarId: string) {
    if (!activeHomeId) return;
    try {
      const result = await api.listSharesForCalendar(activeHomeId, calendarId);
      setShares((current) => ({ ...current, [calendarId]: result.items }));
    } catch (cause) {
      setShareError(
        cause instanceof ApiError ? cause.message : "Could not load calendar sharing.",
      );
    }
  }

  function toggleSharePanel(calendarId: string) {
    setShareError("");
    setShareEmail("");
    setSharePermission("view");
    setSharePanel((current) => {
      const next = current === calendarId ? null : calendarId;
      if (next) void loadShares(next);
      return next;
    });
  }

  async function shareCalendar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || !sharePanel || shareBusy || !shareEmail.trim()) return;
    setShareBusy(true);
    setShareError("");
    try {
      await api.createCalendarShare(activeHomeId, {
        calendar_id: sharePanel,
        recipient_email: shareEmail.trim(),
        permission: sharePermission,
      });
      setShareEmail("");
      setSharePermission("view");
      await loadShares(sharePanel);
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not share that calendar.");
    } finally {
      setShareBusy(false);
    }
  }

  async function changeSharePermission(calendarId: string, shareId: string, permission: "view" | "manage") {
    if (!activeHomeId || shareBusy) return;
    setShareBusy(true);
    setShareError("");
    try {
      await api.changeCalendarSharePermission(activeHomeId, shareId, permission);
      await loadShares(calendarId);
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not change that permission.");
    } finally {
      setShareBusy(false);
    }
  }

  async function revokeShare(calendarId: string, shareId: string) {
    if (!activeHomeId || shareBusy) return;
    if (!window.confirm("Turn off sharing for this person? They'll lose access immediately.")) {
      return;
    }
    setShareBusy(true);
    setShareError("");
    try {
      await api.revokeCalendarShare(activeHomeId, shareId);
      await loadShares(calendarId);
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not revoke that share.");
    } finally {
      setShareBusy(false);
    }
  }

  async function deleteCalendar(calendarId: string) {
    if (!activeHomeId || busy) return;
    if (
      !window.confirm("Delete this category? Its events are deleted too — this can't be undone.")
    ) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.deleteCalendar(activeHomeId, calendarId, { confirmed: true });
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete that category.");
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
            <h1>Event categories</h1>
          </div>
        </div>

        <FormStatus error={error} />

        {!loaded || homeLoading ? (
          <p role="status">Loading event categories…</p>
        ) : (
          <>
            <div className="settings-list">
              {items.map((calendar) => {
                const badge = calendarBadgeLabel(calendar);
                const calendarShares = shares[calendar.id] ?? [];
                return (
                  <div className="card" key={calendar.id}>
                    <div className="settings-list-row">
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
                      <div className="actions compact-actions">
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => toggleSharePanel(calendar.id)}
                        >
                          {sharePanel === calendar.id ? "Close" : "Share calendar"}
                        </button>
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
                    </div>

                    {sharePanel === calendar.id && (
                      <div className="calendar-sharing-panel">
                        <FormStatus error={shareError} />
                        {canShareCalendar(externalInvitesEnabled) ? (
                          <form onSubmit={shareCalendar}>
                            <label>
                              Email address
                              <input
                                type="email"
                                value={shareEmail}
                                onChange={(event) => setShareEmail(event.target.value)}
                                placeholder="grandma@example.com"
                                required
                              />
                            </label>
                            <label>
                              Access
                              <select
                                value={sharePermission}
                                onChange={(event) =>
                                  setSharePermission(event.target.value as "view" | "manage")
                                }
                              >
                                <option value="view">Can view</option>
                                <option value="manage">Can add &amp; edit</option>
                              </select>
                            </label>
                            <button disabled={shareBusy}>
                              {shareBusy ? "Sending…" : "Send invitation"}
                            </button>
                          </form>
                        ) : (
                          <>
                            <p>Sharing a calendar outside the Home is included with MyKhaya Family.</p>
                            <Link className="button secondary" href="/settings/billing">
                              Upgrade to Family
                            </Link>
                          </>
                        )}

                        {calendarShares.length > 0 && (
                          <div className="calendar-share-list">
                            {calendarShares.map((share) => (
                              <div className="calendar-share-row" key={share.id}>
                                <div>
                                  <strong>{share.recipient_email}</strong>
                                  <small>
                                    {share.permission === "manage" ? "Can add & edit" : "Can view"} ·{" "}
                                    {shareStatusLabels[share.status]}
                                    {share.accepted_at
                                      ? ` · Accepted ${new Date(share.accepted_at).toLocaleDateString(
                                          "en-GB",
                                          { day: "numeric", month: "long", year: "numeric" },
                                        )}`
                                      : ""}
                                  </small>
                                </div>
                                {share.status === "accepted" && (
                                  <div className="actions compact-actions">
                                    <select
                                      value={share.permission}
                                      disabled={shareBusy}
                                      onChange={(event) =>
                                        changeSharePermission(
                                          calendar.id,
                                          share.id,
                                          event.target.value as "view" | "manage",
                                        )
                                      }
                                    >
                                      <option value="view">Can view</option>
                                      <option value="manage">Can add &amp; edit</option>
                                    </select>
                                    <button
                                      type="button"
                                      className="secondary"
                                      disabled={shareBusy}
                                      onClick={() => revokeShare(calendar.id, share.id)}
                                    >
                                      Revoke
                                    </button>
                                  </div>
                                )}
                                {(share.status === "pending_recipient" ||
                                  share.status === "pending_admin_approval") && (
                                  <div className="actions compact-actions">
                                    <button
                                      type="button"
                                      className="secondary"
                                      disabled={shareBusy}
                                      onClick={() => revokeShare(calendar.id, share.id)}
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <section className="card details">
              <h2>Add a category</h2>
              {canCreateCalendar(usage) ? (
                <form onSubmit={createCalendar}>
                  <label>
                    Category name
                    <input
                      value={newName}
                      onChange={(event) => setNewName(event.target.value)}
                      maxLength={80}
                      required
                    />
                  </label>
                  <button disabled={busy}>{busy ? "Adding…" : "Add category"}</button>
                </form>
              ) : (
                <>
                  <p>Multiple event categories are included with MyKhaya Family.</p>
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
