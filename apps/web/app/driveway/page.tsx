"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Car, ChevronRight, Plus } from "lucide-react";
import type { BillingStatus, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
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

export default function DrivewayPage() {
  const { activeHomeId } = useActiveHome();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    api.billingStatus(activeHomeId).then(setBilling).catch(() => setBilling(null));
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
              <p className="muted">Keep track of your vehicles, documents and renewals.</p>
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
            <p className="muted">Keep track of your vehicles, documents and renewals.</p>
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
            <div className="section-heading">
              <h2>Your vehicles</h2>
            </div>
            <div className="lists-grid">
              {vehicles.map((vehicle) => {
                const meta = vehicleMeta(vehicle);
                return (
                  <article className="card lists-card" key={vehicle.id}>
                    <Link className="lists-card-body" href={`/driveway/${vehicle.id}`}>
                      <span className="more-icon-tile blue" aria-hidden="true">
                        <Car size={20} strokeWidth={1.75} />
                      </span>
                      <span className="lists-card-copy">
                        <strong>{vehicle.nickname}</strong>
                        <span className="lists-card-status">
                          {vehicle.registration ?? countryName(vehicle.country_code)}
                          {meta ? ` · ${meta}` : ""}
                        </span>
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
