"use client";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Lock } from "lucide-react";
import type { CalendarUsage, EventLabel, Home, HomeCalendar } from "@mykhaya/shared-types";
import { resolveColour, type ColourKey } from "@mykhaya/design-tokens";
import { ApiError, api } from "@mykhaya/api-client";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";

// Mutually exclusive by construction, matching the pattern used on the
// People page — one action's outcome never lingers alongside another's.
type PageStatus =
  | { kind: "idle" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

function CalendarsAndCategories({ homeId }: { homeId: string }) {
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [categoryUsage, setCategoryUsage] = useState<CalendarUsage | null>(null);
  const [status, setStatus] = useState<PageStatus>({ kind: "idle" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [colourEditingId, setColourEditingId] = useState<string | null>(null);
  const [newColourOpen, setNewColourOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColour, setNewColour] = useState<ColourKey>("teal");
  // The primary/system Home calendar — its `name` is a fixed product
  // concept ("Home calendar" — see the copy below), never user-editable,
  // but its colour is (the fallback uncategorised events render with; see
  // routers.calendar.update_calendar, which structurally rejects any
  // client-supplied `name`).
  const [homeCalendar, setHomeCalendar] = useState<HomeCalendar | null>(null);
  const [homeCalendarColourOpen, setHomeCalendarColourOpen] = useState(false);

  // This page is the actual user-facing "event category" resource
  // calendar.max_categories governs (every event belongs to one of these —
  // see the copy below) — not the separate, lower-level Calendar concept.
  // See docs/architecture/commercial-entitlements.md "Event categories are
  // CalendarEventLabel, not HomeCalendar".
  async function load() {
    const [rows, billing, calendars] = await Promise.all([
      api.listLabels(homeId, { includeInactive: true }),
      api.billingStatus(homeId),
      api.listCalendars(homeId),
    ]);
    setLabels(rows);
    setCategoryUsage(billing.category_usage);
    setHomeCalendar(calendars.items.find((row) => row.is_primary) ?? null);
  }

  async function recolourHomeCalendar(colour: ColourKey) {
    if (busy || !homeCalendar) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.updateCalendar(homeId, homeCalendar.id, { color: colour });
      setHomeCalendarColourOpen(false);
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not change that colour.",
      });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load().catch((cause: Error) => setStatus({ kind: "error", message: cause.message }));
  }, [homeId]);

  // Fails closed while loading — the create form/CTA only ever appears
  // once the plan's actual category limit is confirmed, never optimistically.
  const canAddMore = categoryUsage
    ? categoryUsage.limit === null || categoryUsage.count < categoryUsage.limit
    : false;

  async function createLabel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !newName.trim()) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.createLabel(homeId, { name: newName.trim(), color: newColour });
      setNewName("");
      setNewColour("teal");
      setStatus({ kind: "success", message: "Category added." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not add that category.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function renameLabel(label: EventLabel, name: string) {
    if (busy || !name.trim() || name === label.name) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.updateLabel(homeId, label.id, { name: name.trim() });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not rename that category.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function recolourLabel(label: EventLabel, colour: ColourKey) {
    if (busy) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.updateLabel(homeId, label.id, { color: colour });
      setColourEditingId(null);
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not change that colour.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(label: EventLabel) {
    if (busy) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.updateLabel(homeId, label.id, { is_active: !label.is_active });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not update that category.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card details">
      <h2>Categories</h2>
      <p className="muted">
        Categories colour and tag events on your Home calendar — who it&rsquo;s mainly
        for, or what type of event it is. They&rsquo;re not separate calendars; see{" "}
        <Link href="/calendar/calendars">Home calendars</Link> for that.
      </p>
      <FormStatus
        message={status.kind === "success" ? status.message : undefined}
        error={status.kind === "error" ? status.message : undefined}
      />
      {homeCalendar && (
        <ul className="label-list">
          <li className="label-row">
            <div className="label-row-main">
              <button
                type="button"
                className="colour-dot"
                style={{ "--swatch-colour": resolveColour(homeCalendar.color) } as React.CSSProperties}
                aria-label="Change Home calendar colour"
                aria-expanded={homeCalendarColourOpen}
                disabled={busy}
                onClick={() => setHomeCalendarColourOpen((open) => !open)}
              />
              <span>Home calendar</span>
            </div>
            <p className="muted">Shared events without a category</p>
            {homeCalendarColourOpen && (
              <ColourSwatchPicker
                value={homeCalendar.color}
                onChange={recolourHomeCalendar}
                groupLabel="Home calendar colour"
                disabled={busy}
              />
            )}
          </li>
        </ul>
      )}
      <ul className="label-list">
        {labels.map((label) => {
          const locked = label.commercial_access === "read_only_due_to_plan";
          if (locked) {
            return (
              <li key={label.id} className="label-row label-row-locked">
                <div className="label-row-main">
                  <span
                    className="colour-dot"
                    style={{ "--swatch-colour": resolveColour(label.color) } as React.CSSProperties}
                    aria-hidden="true"
                  />
                  <span className="muted label-name-locked">{label.name}</span>
                  <span className="quiet-state label-locked-indicator">
                    <Lock size={14} aria-hidden="true" /> Family
                  </span>
                </div>
              </li>
            );
          }
          return (
            <li key={label.id} className="label-row">
              <div className="label-row-main">
                <button
                  type="button"
                  className="colour-dot"
                  style={{ "--swatch-colour": resolveColour(label.color) } as React.CSSProperties}
                  aria-label={`Change ${label.name} colour`}
                  aria-expanded={colourEditingId === label.id}
                  disabled={busy}
                  onClick={() =>
                    setColourEditingId((current) => (current === label.id ? null : label.id))
                  }
                />
                {editingId === label.id ? (
                  <input
                    type="text"
                    defaultValue={label.name}
                    maxLength={40}
                    disabled={busy}
                    onBlur={(event) => {
                      renameLabel(label, event.target.value);
                      setEditingId(null);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") event.currentTarget.blur();
                      if (event.key === "Escape") setEditingId(null);
                    }}
                    autoFocus
                  />
                ) : (
                  <button
                    type="button"
                    className="tertiary label-name-button"
                    onClick={() => setEditingId(label.id)}
                  >
                    {label.name}
                  </button>
                )}
                <label className="check-row label-active-toggle">
                  <input
                    type="checkbox"
                    checked={label.is_active}
                    disabled={busy || (!label.is_active && !canAddMore)}
                    onChange={() => toggleActive(label)}
                  />
                  Active
                </label>
              </div>
              {colourEditingId === label.id && (
                <ColourSwatchPicker
                  value={label.color}
                  onChange={(colour) => recolourLabel(label, colour)}
                  groupLabel={`${label.name} colour`}
                  disabled={busy}
                />
              )}
            </li>
          );
        })}
      </ul>
      {canAddMore ? (
        <form className="label-create-form" onSubmit={createLabel}>
          <label>
            New category
            <input
              type="text"
              value={newName}
              maxLength={40}
              placeholder="e.g. Sport"
              onChange={(event) => setNewName(event.target.value)}
            />
          </label>
          <div className="label-row-main">
            <button
              type="button"
              className="colour-dot"
              style={{ "--swatch-colour": resolveColour(newColour) } as React.CSSProperties}
              aria-label="Change new category colour"
              aria-expanded={newColourOpen}
              onClick={() => setNewColourOpen((open) => !open)}
            />
            <span className="muted">Colour</span>
          </div>
          {newColourOpen && (
            <ColourSwatchPicker
              value={newColour}
              onChange={(colour) => {
                setNewColour(colour);
                setNewColourOpen(false);
              }}
              groupLabel="New category colour"
              disabled={busy}
            />
          )}
          <button disabled={busy || !newName.trim()}>Add category</button>
        </form>
      ) : (
        <FamilyUpsell
          title="Add another category 🔒"
          description="Unlimited categories are included with MyKhaya Family."
        />
      )}
    </section>
  );
}

export default function HomeSettings() {
  const [home, setHome] = useState<Home | null>(null);
  const { activeHomeId } = useActiveHome();
  useEffect(() => {
    if (!activeHomeId) return;
    api.homes().then((homes) => setHome(homes.find((row) => row.id === activeHomeId) ?? null));
  }, [activeHomeId]);
  const canManageCalendars = home?.capabilities.includes("calendar.edit_all") ?? false;
  return (
    <SettingsPage title="Home settings">
      <section className="card details">
        <h2>{home?.name ?? "Your Home"}</h2>
        <p>
          {home?.member_count ?? 0} people · Your role:{" "}
          {home?.role.replace("_", " ") ?? "—"}
        </p>
        <p className="hint">
          Home ownership transfers and deletion will be added after the recovery
          workflow is independently reviewed.
        </p>
      </section>
      {activeHomeId && canManageCalendars && <CalendarsAndCategories homeId={activeHomeId} />}
    </SettingsPage>
  );
}
