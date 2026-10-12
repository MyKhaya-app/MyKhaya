"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Car, ChevronRight, Plus, ShieldCheck } from "lucide-react";
import type { BillingStatus, Member, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { VehiclePhoto } from "@/components/vehicle-photo";
import { MotPill, OwnerAvatar, PlateChip } from "./driveway-ui";
import {
  dayCount,
  firstName,
  formatShortDate,
  motListLabel,
  motNeedsAttention,
  vehicleMeta,
  vehicleMotState,
  vehicleName,
  type MotState,
} from "./vehicle-display";

// Driveway — everyone's vehicles (Ultimate-only). Reached from More →
// Household Tools → Driveway, never a bottom-nav tab — see
// components/settings-page.tsx. MOT status uses the one shared rule in
// vehicle-display.ts (red at 30 days or fewer, and when expired).

// "all", "mine", or a member's user id.
type Filter = string;

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && (cause.status === 404 || cause.status === 403)) {
    return "Driveway isn't available for this Home right now.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

function GatedPage({ children }: { children: React.ReactNode }) {
  return (
    <AppShellContent>
      <main className="standard-page module-page drv-page">
        <div className="drv-heading">
          <div className="drv-heading-copy">
            <p className="drv-eyebrow">Home</p>
            <h1 className="drv-title">Driveway</h1>
          </div>
        </div>
        {children}
      </main>
    </AppShellContent>
  );
}

/** The summary line above the cards: the most urgent MOT, or "all in date". */
function summaryStrip(vehicles: Vehicle[]): { urgent: boolean; text: string; date: string } | null {
  const states = vehicles
    .filter((vehicle) => vehicle.country_code === "GB")
    .map((vehicle) => ({ vehicle, state: vehicleMotState(vehicle) }))
    .filter((entry): entry is { vehicle: Vehicle; state: MotState & { daysLeft: number } } => entry.state.daysLeft !== null);
  if (states.length === 0) return null;
  states.sort((a, b) => a.state.daysLeft - b.state.daysLeft);
  const first = states[0]!;
  const date = formatShortDate(first.state.dueDate) ?? "";
  if (motNeedsAttention(first.state)) {
    const name = vehicleName(first.vehicle);
    const text =
      first.state.tone === "expired" ? `${name} MOT expired ·` : `${name} MOT due in ${dayCount(first.state.daysLeft)} ·`;
    return { urgent: true, text, date };
  }
  return { urgent: false, text: "All MOTs in date · next due", date };
}

export default function DrivewayPage() {
  const { activeHomeId } = useActiveHome();
  const { user } = useAuth();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    if (!activeHomeId) return;
    api.billingStatus(activeHomeId).then(setBilling).catch(() => setBilling(null));
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
    api
      .featureMatrix(activeHomeId)
      .then((matrix) => setModuleReleased(matrix.features.some((row) => row.feature === "driveway" && row.enabled)))
      .catch(() => setModuleReleased(false));
  }, [activeHomeId]);

  useEffect(() => {
    if (!activeHomeId || moduleReleased !== true || billing?.driveway_enabled !== true) return;
    api
      .vehicles(activeHomeId)
      .then((result) => setVehicles(result.items))
      .catch((cause) => setError(loadErrorMessage(cause, "Could not load your vehicles.")));
  }, [activeHomeId, moduleReleased, billing]);

  const others = useMemo(() => members.filter((member) => member.user_id !== user?.id), [members, user?.id]);
  const memberById = useMemo(() => new Map(members.map((member) => [member.user_id, member])), [members]);
  const ownerId = filter === "all" ? null : filter === "mine" ? user?.id ?? null : filter;
  const visible = vehicles?.filter((vehicle) => ownerId === null || vehicle.owner_user_id === ownerId) ?? null;
  const strip = visible && visible.length > 0 ? summaryStrip(visible) : null;
  const filterMember = filter !== "all" && filter !== "mine" ? memberById.get(filter) : undefined;
  const emptyName = filterMember ? firstName(filterMember.display_name) : filter === "mine" ? "you" : null;

  if (!activeHomeId || !billing || moduleReleased === null) {
    return (
      <GatedPage>
        <p role="status">Loading Driveway…</p>
      </GatedPage>
    );
  }
  if (!moduleReleased) {
    return (
      <GatedPage>
        <p className="empty-mini">Driveway isn't available for this Home yet. Please check back soon.</p>
      </GatedPage>
    );
  }
  if (!billing.driveway_enabled) {
    return (
      <GatedPage>
        <div className="empty-mini">
          <p>Included with MyKhaya Ultimate.</p>
          <Link className="button secondary" href="/settings/billing">
            View plans
          </Link>
        </div>
      </GatedPage>
    );
  }

  const chips: { id: Filter; label: string }[] = [
    { id: "all", label: "All" },
    ...(user ? [{ id: "mine", label: "Mine" }] : []),
    ...others.map((member) => ({ id: member.user_id, label: firstName(member.display_name) })),
  ];

  return (
    <AppShellContent>
      <main className="standard-page module-page drv-page drv-list-page">
        <div className="drv-heading">
          <div className="drv-heading-copy">
            <p className="drv-eyebrow">Home</p>
            <h1 className="drv-title">Driveway</h1>
            <p className="drv-subtitle">Everyone's vehicles, MOTs and key details in one place.</p>
          </div>
          <img className="drv-heading-art" src="/images/Driveway-asset.png" alt="" aria-hidden="true" />
        </div>

        <div className="drv-chips drv-chips-scroll" role="group" aria-label="Filter by person">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className="drv-chip"
              aria-pressed={filter === chip.id}
              onClick={() => setFilter(chip.id)}
            >
              {chip.label}
            </button>
          ))}
        </div>

        <FormStatus error={error} />

        {visible === null ? (
          !error && <p role="status">Loading vehicles…</p>
        ) : visible.length === 0 ? (
          <div className="drv-empty">
            <span className="drv-empty-icon" aria-hidden="true">
              <Car size={28} strokeWidth={1.8} />
            </span>
            <strong>{emptyName ? `No vehicles for ${emptyName} yet` : "No vehicles yet"}</strong>
            <span>Add one with just the registration – we'll look up the MOT.</span>
            <Link
              className="drv-button drv-button-secondary drv-button-compact"
              href={filterMember ? `/driveway/add?owner=${encodeURIComponent(filterMember.user_id)}` : "/driveway/add"}
            >
              {filterMember ? `Add a vehicle for ${emptyName}` : "Add a vehicle"}
            </Link>
          </div>
        ) : (
          <div className="drv-list">
            {strip && (
              <p className={`drv-strip${strip.urgent ? " drv-strip-urgent" : ""}`}>
                <ShieldCheck size={20} aria-hidden="true" />
                <span>
                  {strip.text} <strong>{strip.date}</strong>
                </span>
              </p>
            )}
            <ul className="drv-cards" aria-label="Vehicles">
              {visible.map((vehicle) => {
                const name = vehicleName(vehicle);
                const owner = memberById.get(vehicle.owner_user_id);
                const ownerName = owner?.display_name ?? (vehicle.owner_user_id === user?.id ? user.display_name : "Home member");
                const meta = vehicle.make && vehicle.model ? vehicleMeta(vehicle) : "Add make and model";
                const state = vehicleMotState(vehicle);
                return (
                  <li key={vehicle.id}>
                    <Link className="drv-card drv-vehicle-card" href={`/driveway/${vehicle.id}`}>
                      <span className={`drv-thumb${vehicle.photo_version ? "" : " drv-thumb-empty"}`} aria-hidden="true">
                        <VehiclePhoto homeId={vehicle.group_id} vehicleId={vehicle.id} version={vehicle.photo_version} label="" />
                      </span>
                      <span className="drv-vehicle-body">
                        <span className="drv-vehicle-top">
                          <span className="drv-vehicle-name">{name}</span>
                          <OwnerAvatar userId={vehicle.owner_user_id} name={ownerName} colour={owner?.colour} />
                        </span>
                        <span className="drv-vehicle-meta">
                          <PlateChip registration={vehicle.registration} />
                          {meta && <span className="drv-vehicle-meta-text">{meta}</span>}
                        </span>
                        {vehicle.country_code === "GB" && (
                          <MotPill tone={state.tone} variant="list">
                            {motListLabel(state)}
                          </MotPill>
                        )}
                      </span>
                      <ChevronRight size={18} className="drv-chevron" aria-hidden="true" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <Link className="button rr-fab drv-fab" href="/driveway/add">
          <Plus size={20} strokeWidth={2.4} aria-hidden="true" />
          <span>Add vehicle</span>
        </Link>
      </main>
    </AppShellContent>
  );
}
