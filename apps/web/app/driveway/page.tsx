"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Car, ChevronRight, Plus } from "lucide-react";
import type { BillingStatus, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { VehiclePhoto } from "@/components/vehicle-photo";
import { countryName } from "./countries";

// Driveway — vehicle management (Ultimate-only). Phase 3 ships the mobile
// consumer UI for the Phase 2 core vehicle model only: no DVLA/DVSA lookup,
// MOT/tax data, reminders, documents, service history, insurance or notes
// yet (later phases). Reached from More → Household Tools → Driveway, never
// a bottom-nav tab — see components/settings-page.tsx.

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && (cause.status === 404 || cause.status === 403)) {
    return "Driveway isn't available for this Home right now.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

function vehicleMeta(vehicle: Vehicle): string | null {
  const parts = [
    vehicle.year ? String(vehicle.year) : null,
    vehicle.fuel_type,
    vehicle.colour,
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : null;
}

function vehicleStatus(status: string | null, date: string | null, label: string): string | null {
  if (!status) return null;
  const formatted = date ? new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : null;
  return `${label}: ${status}${formatted ? ` · ${formatted}` : ""}`;
}

export default function DrivewayPage() {
  const { activeHomeId } = useActiveHome();
  const { user } = useAuth();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [members, setMembers] = useState<{ user_id: string; display_name: string }[]>([]);

  useEffect(() => {
    if (!activeHomeId) return;
    api.billingStatus(activeHomeId).then(setBilling).catch(() => setBilling(null));
    api.members(activeHomeId).then((items) => setMembers(items.map((item) => ({ user_id: item.user_id, display_name: item.display_name })))).catch(() => setMembers([]));
    api
      .featureMatrix(activeHomeId)
      .then((matrix) =>
        setModuleReleased(matrix.features.some((row) => row.feature === "driveway" && row.enabled)),
      )
      .catch(() => setModuleReleased(false));
  }, [activeHomeId]);

  async function load() {
    if (!activeHomeId) return;
    try {
      const result = await api.vehicles(activeHomeId);
      setVehicles(result.items);
    } catch (cause) {
      setError(loadErrorMessage(cause, "Could not load your vehicles."));
    }
  }

  useEffect(() => {
    if (!activeHomeId || moduleReleased !== true || billing?.driveway_enabled !== true) return;
    void load();
  }, [activeHomeId, moduleReleased, billing]);

  const visibleVehicles = vehicles?.filter((vehicle) => ownerFilter === "all" || vehicle.owner_user_id === ownerFilter) ?? null;
  const ownerName = (ownerId: string) => members.find((member) => member.user_id === ownerId)?.display_name ?? (ownerId === user?.id ? "You" : "Home member");

  if (!activeHomeId || !billing || moduleReleased === null) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          <p role="status">Loading Driveway…</p>
        </main>
      </AppShellContent>
    );
  }

  if (!moduleReleased) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                <Car size={14} aria-hidden="true" /> Driveway
              </p>
              <h1>Driveway</h1>
            </div>
          </div>
          <p className="empty-mini">Driveway isn't available for this Home yet. Please check back soon.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!billing.driveway_enabled) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                <Car size={14} aria-hidden="true" /> Driveway
              </p>
              <h1>Driveway</h1>
              <p className="muted">Keep the important bits about your vehicles in one place.</p>
            </div>
          </div>
          <div className="empty-mini">
            <p>Included with MyKhaya Ultimate.</p>
            <Link className="button secondary" href="/settings/billing">
              View plans
            </Link>
          </div>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page module-page driveway-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              <Car size={14} aria-hidden="true" /> Driveway
            </p>
            <h1>Driveway</h1>
              <p className="muted">Keep the important bits about your vehicles in one place.</p>
              <img className="driveway-heading-art" src="/images/Driveway-asset.png" alt="" aria-hidden="true" />
          </div>
        </div>
        <FormStatus error={error} />

        {vehicles === null ? (
          <p role="status">Loading vehicles…</p>
        ) : vehicles.length === 0 ? (
          <div className="meal-empty-state">
            <p>
              <strong>Your Driveway is empty</strong>
            </p>
            <p className="muted">
              Add a vehicle and MyKhaya can help you keep track of the important bits.
            </p>
            <Link className="button secondary" href="/driveway/add">
              <Plus size={16} aria-hidden="true" /> Add vehicle
            </Link>
          </div>
        ) : (
          <>
            <div className="driveway-owner-filters" aria-label="Filter vehicles by owner">
              <button type="button" className={ownerFilter === "all" ? "active" : ""} onClick={() => setOwnerFilter("all")}>All</button>
              {user && <button type="button" className={ownerFilter === user.id ? "active" : ""} onClick={() => setOwnerFilter(user.id)}>Mine</button>}
              {members.filter((member) => member.user_id !== user?.id).map((member) => <button type="button" className={ownerFilter === member.user_id ? "active" : ""} key={member.user_id} onClick={() => setOwnerFilter(member.user_id)}>{member.display_name}</button>)}
            </div>
            <div className="lists-grid">
              {visibleVehicles?.map((vehicle) => {
                const meta = vehicleMeta(vehicle);
                const tax = vehicleStatus(vehicle.tax_status, vehicle.tax_due_date, "Tax");
                const mot = vehicleStatus(vehicle.inspection_status, vehicle.inspection_due_date, "MOT");
                return (
                  <article className="card lists-card driveway-vehicle-card" key={vehicle.id}>
                    <Link className="lists-card-body" href={`/driveway/${vehicle.id}`}>
                      <span className="driveway-vehicle-image" aria-hidden="true">
                        <VehiclePhoto homeId={vehicle.group_id} vehicleId={vehicle.id} version={vehicle.photo_version} label="" />
                      </span>
                      <span className="lists-card-copy">
                        <strong>{vehicle.nickname}</strong>
                        <span className="lists-card-status">
                          {vehicle.registration ?? countryName(vehicle.country_code)}
                          {meta ? ` · ${meta}` : ""}
                        </span>
                        <span className="driveway-owner-badge">{ownerName(vehicle.owner_user_id)}</span>
                        {(tax || mot) && <span className="driveway-statuses">{[tax, mot].filter(Boolean).join(" · ")}</span>}
                      </span>
                      <ChevronRight size={18} className="lists-card-chevron" aria-hidden="true" />
                    </Link>
                  </article>
                );
              })}
            </div>
          </>
        )}

        <Link className="button rr-fab" aria-label="Add vehicle" href="/driveway/add">
          <Plus size={22} aria-hidden="true" />
          <span aria-hidden="true">Add</span>
        </Link>
      </main>
    </AppShellContent>
  );
}
