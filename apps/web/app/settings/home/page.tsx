"use client";
import { FormEvent, useEffect, useState } from "react";
import type { EventLabel, Home } from "@mykhaya/shared-types";
import { resolveColour, type ColourKey } from "@mykhaya/design-tokens";
import { ApiError, api } from "@mykhaya/api-client";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
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
  const [status, setStatus] = useState<PageStatus>({ kind: "idle" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [colourEditingId, setColourEditingId] = useState<string | null>(null);
  const [newColourOpen, setNewColourOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColour, setNewColour] = useState<ColourKey>("teal");

  async function load() {
    const rows = await api.listLabels(homeId);
    setLabels(rows);
  }

  useEffect(() => {
    load().catch((cause: Error) => setStatus({ kind: "error", message: cause.message }));
  }, [homeId]);

  async function createLabel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !newName.trim()) return;
    setBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.createLabel(homeId, { name: newName.trim(), color: newColour });
      setNewName("");
      setNewColour("teal");
      setStatus({ kind: "success", message: "Calendar added." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not add that calendar.",
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
        message: cause instanceof ApiError ? cause.message : "Could not rename that calendar.",
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
        message: cause instanceof ApiError ? cause.message : "Could not update that calendar.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card details">
      <h2>Calendars &amp; categories</h2>
      <p className="muted">
        Every event belongs to one of these — its colour, not who created it, is what
        shows on Calendar.
      </p>
      <FormStatus
        message={status.kind === "success" ? status.message : undefined}
        error={status.kind === "error" ? status.message : undefined}
      />
      <ul className="label-list">
        {labels.map((label) => (
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
                  disabled={busy}
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
        ))}
      </ul>
      <form className="label-create-form" onSubmit={createLabel}>
        <label>
          New calendar or category
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
            aria-label="Change new calendar colour"
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
            groupLabel="New calendar colour"
            disabled={busy}
          />
        )}
        <button disabled={busy || !newName.trim()}>Add calendar</button>
      </form>
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
