"use client";

import Link from "next/link";
import { FormEvent, use, useEffect, useState } from "react";
import { Car, Check, ChevronLeft, Sparkles } from "lucide-react";
import type { Member, Vehicle, VehicleMotNudgeOffset, VehicleMotNudgePlan } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { PlateChip } from "../../../driveway-ui";
import { firstName, formatShortDate, joinWithAnd, vehicleName } from "../../../vehicle-display";

// New MOT reminder (Nudges), pre-filled from the vehicle's MOT. Saving
// stores the owner's MOT nudge plan: one ordinary Nudges reminder per chosen
// lead day, for the vehicle's owner (MOT nudges are as private as the
// vehicle's other reminders). A repeating plan moves on after the next pass.

const WHENS: { offset: VehicleMotNudgeOffset; label: string }[] = [
  { offset: 30, label: "30 days before" },
  { offset: 14, label: "14 days before" },
  { offset: 7, label: "7 days before" },
  { offset: 0, label: "On the day" },
];

type Origin = "vehicle" | "vehicle-mot" | "history" | "nudges";

function originFromUrl(): Origin {
  if (typeof window === "undefined") return "vehicle";
  const value = new URLSearchParams(window.location.search).get("from");
  return value === "history" || value === "vehicle-mot" || value === "nudges" ? value : "vehicle";
}

function backHref(vehicleId: string, origin: Origin): string {
  if (origin === "nudges") return "/settings/routines-reminders";
  if (origin === "history") return `/driveway/${vehicleId}/mot`;
  if (origin === "vehicle-mot") return `/driveway/${vehicleId}?tab=mot`;
  return `/driveway/${vehicleId}`;
}

export default function NewMotReminderPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
  const { user } = useAuth();
  const [origin, setOrigin] = useState<Origin>("vehicle");
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [ready, setReady] = useState(false);
  const [blocked, setBlocked] = useState("");
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [offsets, setOffsets] = useState<VehicleMotNudgeOffset[]>([30, 7]);
  const [repeat, setRepeat] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<VehicleMotNudgePlan | null>(null);

  useEffect(() => setOrigin(originFromUrl()), []);

  useEffect(() => {
    if (!activeHomeId) return;
    let cancelled = false;
    (async () => {
      try {
        const nextVehicle = await api.vehicle(activeHomeId, vehicleId);
        if (cancelled) return;
        setVehicle(nextVehicle);
        api.members(activeHomeId).then((items) => !cancelled && setMembers(items)).catch(() => undefined);
        if (nextVehicle.country_code !== "GB") {
          setBlocked("MOT reminders are only available for vehicles registered in the UK.");
          return;
        }
        const [existing, mot] = await Promise.all([
          api.vehicleMotNudges(activeHomeId, vehicleId),
          api.vehicleMot(activeHomeId, vehicleId).catch(() => null),
        ]);
        if (cancelled) return;
        const plan = existing.plan;
        setTitle(plan?.title ?? `Book MOT – ${vehicleName(nextVehicle)}`);
        setDueDate(plan?.due_date ?? mot?.summary.due_date ?? "");
        setOffsets(plan ? plan.offsets : [30, 7]);
        setRepeat(plan ? plan.repeat : true);
        setReady(true);
      } catch (cause) {
        if (cancelled) return;
        setBlocked(
          cause instanceof ApiError && cause.status === 404
            ? "Only the person this vehicle belongs to (or a Home Admin) can set its MOT reminders."
            : cause instanceof ApiError
              ? cause.message
              : "Could not load this vehicle.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeHomeId, vehicleId]);

  const name = vehicle ? vehicleName(vehicle) : "Vehicle";
  const href = backHref(vehicleId, origin);
  const isMine = vehicle?.owner_user_id === user?.id;
  const owner = members.find((member) => member.user_id === vehicle?.owner_user_id);
  const recipientLabel = isMine ? "Me" : owner ? firstName(owner.display_name) : "Vehicle owner";
  const recipientWords = isMine ? "you" : owner ? firstName(owner.display_name) : "the vehicle's owner";

  function toggle(offset: VehicleMotNudgeOffset) {
    setOffsets((current) => (current.includes(offset) ? current.filter((item) => item !== offset) : [...current, offset]));
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || saving) return;
    if (!title.trim()) return setError("Give the reminder a name.");
    if (!dueDate) return setError("Add the date this MOT expires.");
    if (offsets.length === 0) return setError("Choose at least one time to be nudged.");
    setSaving(true);
    setError("");
    try {
      const result = await api.saveVehicleMotNudges(activeHomeId, vehicleId, { title: title.trim(), due_date: dueDate, offsets, repeat });
      setSaved(result.plan);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "We couldn't save this reminder. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const summary = saved
    ? `${
        saved.scheduled.length
          ? `We'll nudge ${recipientWords} on ${joinWithAnd(saved.scheduled.map((day) => formatShortDate(day) ?? day))}.`
          : "Those nudge dates have already passed, so there's nothing to send this time."
      }${saved.repeat ? " It repeats each year after the next pass." : ""}`
    : "";

  return (
    <AppShellContent>
      <main className="standard-page module-page drv-page drv-nudge-page">
        <Link className="drv-back" href={href}>
          <ChevronLeft size={18} aria-hidden="true" /> {origin === "nudges" ? "Nudges" : name}
        </Link>
        <div className="drv-heading-copy">
          <p className="drv-eyebrow">Nudges</p>
          <h1 className="drv-title drv-title-section">New reminder</h1>
        </div>

        {blocked ? (
          <p className="empty-mini">{blocked}</p>
        ) : !ready || !vehicle ? (
          <p role="status">Loading…</p>
        ) : saved ? (
          <section className="drv-card drv-saved" aria-live="polite">
            <span className="drv-saved-icon" aria-hidden="true">
              <Check size={30} strokeWidth={2.4} />
            </span>
            <h2>Nudge saved</h2>
            <p>{summary}</p>
            <Link className="drv-button drv-button-primary drv-button-full" href={`/driveway/${vehicleId}`}>
              Back to {name}
            </Link>
            <button type="button" className="drv-text-button" onClick={() => setSaved(null)}>
              Edit nudge
            </button>
          </section>
        ) : (
          <form className="drv-nudge-form" onSubmit={save} noValidate>
            <p className="drv-info">
              <Sparkles size={20} aria-hidden="true" />
              <span>Filled in from your MOT record. Check it over and save.</span>
            </p>

            <section className="drv-card drv-form-card">
              <div className="drv-field">
                <label htmlFor="nudge-title">Reminder</label>
                <input id="nudge-title" className="drv-input" type="text" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
              </div>
              <div className="drv-field">
                <span className="drv-field-label" id="nudge-linked">
                  Linked to
                </span>
                <div className="drv-linked" aria-labelledby="nudge-linked">
                  <Car size={20} strokeWidth={1.8} aria-hidden="true" />
                  <span className="drv-linked-name">{name}</span>
                  <PlateChip registration={vehicle.registration} />
                </div>
              </div>
              <div className="drv-field">
                <label htmlFor="nudge-date">MOT expires</label>
                <input id="nudge-date" className="drv-input" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
              </div>
            </section>

            <section className="drv-card drv-form-card drv-form-card-tight" aria-labelledby="nudge-when">
              <h2 id="nudge-when" className="drv-form-heading">
                Nudge me
              </h2>
              <div className="drv-chips drv-chips-wrap" role="group" aria-labelledby="nudge-when">
                {WHENS.map((item) => (
                  <button key={item.offset} type="button" className="drv-chip" aria-pressed={offsets.includes(item.offset)} onClick={() => toggle(item.offset)}>
                    {item.label}
                  </button>
                ))}
              </div>
              <p className="drv-muted-small">You can get an MOT up to a month (minus a day) early and keep the same renewal date.</p>
            </section>

            <section className="drv-card drv-form-card drv-form-card-tight" aria-labelledby="nudge-who">
              <h2 id="nudge-who" className="drv-form-heading">
                Who should get it?
              </h2>
              <div className="drv-chips drv-chips-wrap" role="group" aria-labelledby="nudge-who">
                <button type="button" className="drv-chip" aria-pressed={true} aria-disabled="true" aria-describedby="nudge-who-note">
                  {recipientLabel}
                </button>
              </div>
              <p className="drv-muted-small" id="nudge-who-note">
                MOT nudges go to whoever the vehicle belongs to.
              </p>
              <div className="drv-repeat">
                <span className="drv-repeat-copy">
                  <span className="drv-repeat-title" id="nudge-repeat-label">
                    Repeat every year
                  </span>
                  <span className="drv-muted-small">Moves on automatically after the next pass</span>
                </span>
                <button
                  type="button"
                  role="switch"
                  className="drv-switch"
                  aria-checked={repeat}
                  aria-labelledby="nudge-repeat-label"
                  onClick={() => setRepeat((value) => !value)}
                >
                  <span className="drv-switch-knob" aria-hidden="true" />
                </button>
              </div>
            </section>

            <FormStatus error={error} />
            <button type="submit" className="drv-button drv-button-primary drv-button-tall" disabled={saving} aria-busy={saving}>
              {saving ? "Saving…" : "Save nudge"}
            </button>
            <Link className="drv-text-link drv-text-link-muted" href={href}>
              Cancel
            </Link>
          </form>
        )}
      </main>
    </AppShellContent>
  );
}
