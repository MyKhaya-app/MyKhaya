"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { CalendarShare, EventLabel, HomeCalendar } from "@mykhaya/shared-types";
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

function shareCategorySummary(share: CalendarShare, labelsById: Map<string, EventLabel>): string {
  if (share.category_ids === null) return "Entire calendar";
  if (share.category_ids.length === 0) return "No categories selected";
  return share.category_ids.map((id) => labelsById.get(id)?.name ?? "Unknown category").join(", ");
}

// Calendar management — three distinct concepts, kept visually and
// structurally separate (see docs on Home/Personal/Shared calendars vs
// categories): this Home's own calendar(s) and their sharing, the
// signed-in user's Personal calendar, and calendars genuinely shared with
// them by other Homes. Categories (CalendarEventLabel — Family, Megan,
// Activity, ...) are managed on Home settings, deliberately not here: they
// colour/tag events within the Home calendar, they are never a calendar of
// their own — see /settings/home's "Categories" section.
export default function CalendarsPage() {
  const { activeHome, activeHomeId, loading: homeLoading } = useActiveHome();
  const [items, setItems] = useState<HomeCalendar[]>([]);
  const [personalCalendar, setPersonalCalendar] = useState<HomeCalendar | null>(null);
  const [limit, setLimit] = useState<number | null>(null);
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [sharedWithYou, setSharedWithYou] = useState<CalendarShare[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [sharePanel, setSharePanel] = useState<string | null>(null);
  const [shareEmail, setShareEmail] = useState("");
  const [sharePermission, setSharePermission] = useState<"view" | "manage">("view");
  const [shareScope, setShareScope] = useState<"entire" | "selected">("entire");
  const [shareCategoryIds, setShareCategoryIds] = useState<Set<string>>(new Set());
  const [shares, setShares] = useState<Record<string, CalendarShare[]>>({});
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState("");
  const [externalInvitesEnabled, setExternalInvitesEnabled] = useState(false);

  const labelsById = new Map(labels.map((label) => [label.id, label]));

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
      const [calendars, labelRows, shared] = await Promise.all([
        api.listCalendars(activeHomeId),
        api.listLabels(activeHomeId).catch(() => []),
        api.sharedCalendars().catch(() => ({ items: [] })),
      ]);
      setItems(calendars.items);
      setLimit(calendars.limit);
      setPersonalCalendar(calendars.personal_calendar);
      setLabels(labelRows);
      setSharedWithYou(shared.items);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load your calendars.");
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

  async function loadShares(calendarId: string) {
    if (!activeHomeId) return;
    try {
      const result = await api.listSharesForCalendar(activeHomeId, calendarId);
      setShares((current) => ({ ...current, [calendarId]: result.items }));
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not load calendar sharing.");
    }
  }

  function toggleSharePanel(calendarId: string) {
    setShareError("");
    setShareEmail("");
    setSharePermission("view");
    setShareScope("entire");
    setShareCategoryIds(new Set());
    setSharePanel((current) => {
      const next = current === calendarId ? null : calendarId;
      if (next) void loadShares(next);
      return next;
    });
  }

  function toggleShareCategory(id: string) {
    setShareCategoryIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
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
        category_ids: shareScope === "selected" ? [...shareCategoryIds] : undefined,
      });
      setShareEmail("");
      setSharePermission("view");
      setShareScope("entire");
      setShareCategoryIds(new Set());
      await loadShares(sharePanel);
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not share that calendar.");
    } finally {
      setShareBusy(false);
    }
  }

  async function changeSharePermission(
    calendarId: string,
    shareId: string,
    permission: "view" | "manage",
  ) {
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
      !window.confirm("Delete this calendar? Its events are deleted too — this can't be undone.")
    ) {
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

  function sharingPanel(calendar: HomeCalendar) {
    const calendarShares = shares[calendar.id] ?? [];
    return (
      sharePanel === calendar.id && (
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
                  onChange={(event) => setSharePermission(event.target.value as "view" | "manage")}
                >
                  <option value="view">Can view</option>
                  <option value="manage">Can add &amp; edit</option>
                </select>
              </label>
              {labels.length > 0 && (
                <fieldset className="share-scope-fieldset">
                  <legend>What to share</legend>
                  <label className="check-row">
                    <input
                      type="radio"
                      name={`scope-${calendar.id}`}
                      checked={shareScope === "entire"}
                      onChange={() => setShareScope("entire")}
                    />
                    Entire calendar
                  </label>
                  <label className="check-row">
                    <input
                      type="radio"
                      name={`scope-${calendar.id}`}
                      checked={shareScope === "selected"}
                      onChange={() => setShareScope("selected")}
                    />
                    Selected categories only
                  </label>
                  {shareScope === "selected" && (
                    <div className="share-category-list">
                      {labels.map((label) => (
                        <label className="check-row" key={label.id}>
                          <input
                            type="checkbox"
                            checked={shareCategoryIds.has(label.id)}
                            onChange={() => toggleShareCategory(label.id)}
                          />
                          {label.name}
                        </label>
                      ))}
                    </div>
                  )}
                </fieldset>
              )}
              <button disabled={shareBusy}>{shareBusy ? "Sending…" : "Send invitation"}</button>
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
                      {shareStatusLabels[share.status]} · {shareCategorySummary(share, labelsById)}
                      {share.accepted_at
                        ? ` · Accepted ${new Date(share.accepted_at).toLocaleDateString("en-GB", {
                            day: "numeric",
                            month: "long",
                            year: "numeric",
                          })}`
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
      )
    );
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Calendar</p>
            <h1>Home calendars</h1>
            <p className="muted">
              {activeHome?.name ?? "Your Home"}&rsquo;s own calendar and sharing. Categories
              (Family, Megan, Activity...) live on{" "}
              <Link href="/settings/home">Home settings</Link>.
            </p>
          </div>
        </div>

        <FormStatus error={error} />

        {!loaded || homeLoading ? (
          <p role="status">Loading your calendars…</p>
        ) : (
          <>
            <div className="settings-list">
              {items.map((calendar) => {
                const badge = calendarBadgeLabel(calendar);
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
                          {sharePanel === calendar.id ? "Close" : "Manage sharing"}
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
                    {sharingPanel(calendar)}
                  </div>
                );
              })}
            </div>

            <section className="card details">
              <h2>Add a Home calendar</h2>
              <p className="muted">
                A second shared calendar for this Home — separate from categories, which colour
                and tag events within a calendar rather than containing their own.
              </p>
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
                  <p>Multiple Home calendars are included with MyKhaya Family.</p>
                  {atLimit && <p className="quiet-state">{atLimit}</p>}
                  <Link className="button secondary" href="/settings/billing">
                    Upgrade to Family
                  </Link>
                </>
              )}
            </section>

            {personalCalendar && (
              <section className="card details">
                <h2>Personal calendar</h2>
                <p className="muted">Only visible to you — never automatically shared with your Home.</p>
                <p>
                  <Link href="/settings/home">Calendar colour and settings</Link>
                </p>
              </section>
            )}

            <section className="card details">
              <h2>Shared with you</h2>
              {sharedWithYou.length === 0 ? (
                <p className="quiet-state">
                  No one has shared a calendar with you yet. When they do, it will appear here and
                  overlay your normal Calendar automatically.
                </p>
              ) : (
                <div className="calendar-share-list">
                  {sharedWithYou.map((share) => (
                    <div className="calendar-share-row" key={share.id}>
                      <div>
                        <strong>{share.calendar_name}</strong>
                        <small>
                          {share.source_group_name} ·{" "}
                          {share.permission === "manage" ? "Can add & edit" : "Can view"}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p>
                <Link href="/calendar/shared">Manage notification &amp; briefing preferences</Link>
              </p>
            </section>
          </>
        )}
      </main>
    </AppShell>
  );
}
