"use client";

import Link from "next/link";
import { FormEvent, use, useEffect, useState } from "react";
import { ChevronLeft, Plus, Trash2 } from "lucide-react";
import type { Reminder, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { nudgeCardDateLabel } from "@/app/home/routine-utils";

// Driveway's Reminders page — Phase 4. Every row here is an ordinary Nudges
// Reminder (see mykhaya.driveway_reminders): this page only ever shows/
// creates them through the vehicle-scoped Driveway routes, never a second
// reminder system. Editing/removing an existing reminder from Nudges itself
// removes it here too — same underlying row, no duplicate state.

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That vehicle could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

function formatDueTime(dueTime: string): string {
  return dueTime.slice(0, 5);
}

export default function VehicleRemindersPage({
  params,
}: {
  params: Promise<{ vehicleId: string }>;
}) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [reminders, setReminders] = useState<Reminder[] | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  async function load() {
    if (!activeHomeId) return;
    try {
      const [vehicleRow, reminderRows] = await Promise.all([
        api.vehicle(activeHomeId, vehicleId),
        api.vehicleReminders(activeHomeId, vehicleId),
      ]);
      setVehicle(vehicleRow);
      setReminders(reminderRows.items);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
      else setError(loadErrorMessage(cause, "Could not load this vehicle's reminders."));
    }
  }

  useEffect(() => {
    void load();
  }, [activeHomeId, vehicleId]);

  async function removeReminder(reminder: Reminder) {
    if (!activeHomeId) return;
    if (!window.confirm(`Remove "${reminder.title}"? This will remove the reminder from Nudges too.`)) {
      return;
    }
    try {
      await api.deleteReminder(activeHomeId, reminder.id);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove that reminder.");
    }
  }

  if (notFound) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <Link className="tertiary" href="/driveway">
            <ChevronLeft size={16} aria-hidden="true" /> Driveway
          </Link>
          <p className="empty-mini">That vehicle could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!activeHomeId || !vehicle) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading reminders…</p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page">
        <Link className="tertiary" href={`/driveway/${vehicle.id}`}>
          <ChevronLeft size={16} aria-hidden="true" /> {vehicle.nickname}
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Reminders</p>
            <h1>{vehicle.nickname}</h1>
          </div>
        </div>
        <FormStatus error={error} />

        {reminders === null ? (
          <p role="status">Loading reminders…</p>
        ) : reminders.length === 0 ? (
          <div className="meal-empty-state">
            <p>
              <strong>No reminders yet</strong>
            </p>
            <p className="muted">
              Add a reminder for anything you want MyKhaya to keep an eye on for this vehicle.
            </p>
            <button type="button" className="button secondary" onClick={() => setAdding(true)}>
              <Plus size={16} aria-hidden="true" /> Add reminder
            </button>
          </div>
        ) : (
          <>
            <div className="lists-grid">
              {reminders.map((reminder) => (
                <article className="card lists-card" key={reminder.id}>
                  <span className="lists-card-body">
                    <span className="lists-card-copy">
                      <strong>{reminder.title}</strong>
                      <span className="lists-card-status">
                        {nudgeCardDateLabel(reminder.due_date)} · {formatDueTime(reminder.due_time)}
                        {" · "}
                        {reminder.scope === "personal" ? "Personal" : "Household"}
                        {reminder.category ? ` · ${reminder.category.name}` : ""}
                      </span>
                    </span>
                  </span>
                  <button
                    type="button"
                    className="icon-button secondary"
                    aria-label={`Remove ${reminder.title}`}
                    onClick={() => void removeReminder(reminder)}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </article>
              ))}
            </div>
            <button type="button" className="button rr-fab" aria-label="Add reminder" onClick={() => setAdding(true)}>
              <Plus size={22} aria-hidden="true" />
              <span aria-hidden="true">Add</span>
            </button>
          </>
        )}

        {adding && (
          <AddReminderSheet
            homeId={activeHomeId}
            vehicleId={vehicle.id}
            onClose={() => setAdding(false)}
            onCreated={async () => {
              setAdding(false);
              await load();
            }}
          />
        )}
      </main>
    </AppShellContent>
  );
}

function AddReminderSheet({
  homeId,
  vehicleId,
  onClose,
  onCreated,
}: {
  homeId: string;
  vehicleId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("09:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!title.trim() || !dueDate) {
      setError("Add a title and a due date to continue.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createVehicleReminder(homeId, vehicleId, {
        title: title.trim(),
        due_date: dueDate,
        due_time: dueTime,
      });
      await onCreated();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add this reminder.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="Add reminder" onDismiss={onClose}>
      <form onSubmit={submit} noValidate>
        <FormStatus error={error} />
        <label>
          Title
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={160}
            required
            placeholder="MOT due"
          />
        </label>
        <label>
          Due date
          <input
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            required
          />
        </label>
        <label>
          Due time
          <input type="time" value={dueTime} onChange={(event) => setDueTime(event.target.value)} />
        </label>
        <button className="sheet-primary" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add reminder"}
        </button>
      </form>
    </BottomSheet>
  );
}
