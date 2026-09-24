"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { Bell, ChevronLeft, Info, Trash2 } from "lucide-react";
import type { Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { countryName } from "../countries";

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That vehicle could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function VehicleDetailPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
  const router = useRouter();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    setNotFound(false);
    api
      .vehicle(activeHomeId, vehicleId)
      .then(setVehicle)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
        else setError(loadErrorMessage(cause, "Could not load this vehicle."));
      });
  }, [activeHomeId, vehicleId]);

  async function removeVehicle() {
    if (!activeHomeId || !vehicle) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await api.deleteVehicle(activeHomeId, vehicle.id);
      router.push("/driveway");
    } catch (cause) {
      setDeleteError(cause instanceof ApiError ? cause.message : "Could not remove this vehicle.");
      setDeleteBusy(false);
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
          <p role="status">Loading vehicle…</p>
        </main>
      </AppShellContent>
    );
  }

  const rows: { label: string; value: string }[] = [
    { label: "Make / model", value: [vehicle.make, vehicle.model].filter(Boolean).join(" ") },
    { label: "Registration", value: vehicle.registration ?? "" },
    { label: "Year", value: vehicle.year ? String(vehicle.year) : "" },
    { label: "Fuel", value: vehicle.fuel_type ?? "" },
    { label: "Colour", value: vehicle.colour ?? "" },
    { label: "Country", value: countryName(vehicle.country_code) },
  ].filter((row) => row.value);

  return (
    <AppShellContent>
      <main className="standard-page driveway-detail-page">
        <Link className="tertiary" href="/driveway">
          <ChevronLeft size={16} aria-hidden="true" /> Driveway
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Vehicle</p>
            <h1>{vehicle.nickname}</h1>
            {vehicle.registration && <p className="muted">{vehicle.registration}</p>}
          </div>
        </div>
        <FormStatus error={error} />

        <div className="card-stack">
          {rows.length > 0 && (
            <section className="card details">
              <dl>
                {rows.map((row) => (
                  <div key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          <section className="card more-group">
            <div className="more-group-rows">
              <Link className="more-row" href={`/driveway/${vehicle.id}/details`}>
                <span className="more-icon-tile sage" aria-hidden="true">
                  <Info size={20} strokeWidth={1.75} />
                </span>
                <span className="more-row-text">
                  <h2>Vehicle details</h2>
                  <p>Edit make, model, registration and more</p>
                </span>
                <span className="more-row-chevron" aria-hidden="true">
                  ›
                </span>
              </Link>
              <Link className="more-row" href={`/driveway/${vehicle.id}/reminders`}>
                <span className="more-icon-tile blue" aria-hidden="true">
                  <Bell size={20} strokeWidth={1.75} />
                </span>
                <span className="more-row-text">
                  <h2>Reminders</h2>
                  <p>MOT, tax, service and anything else to keep an eye on</p>
                </span>
                <span className="more-row-chevron" aria-hidden="true">
                  ›
                </span>
              </Link>
            </div>
          </section>

          <button type="button" className="danger-link" onClick={() => setConfirmingDelete(true)}>
            <Trash2 size={16} aria-hidden="true" /> Remove vehicle
          </button>
        </div>

        {confirmingDelete && (
          <BottomSheet
            title="Remove vehicle?"
            onDismiss={() => {
              if (!deleteBusy) setConfirmingDelete(false);
            }}
          >
            <p>This will remove {vehicle.nickname} from Driveway.</p>
            {deleteError && (
              <p className="notice error" role="alert">
                {deleteError}
              </p>
            )}
            <div className="sheet-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setConfirmingDelete(false)}
                disabled={deleteBusy}
              >
                Cancel
              </button>
              <button type="button" className="danger" onClick={() => void removeVehicle()} disabled={deleteBusy}>
                {deleteBusy ? "Removing…" : "Remove vehicle"}
              </button>
            </div>
          </BottomSheet>
        )}
      </main>
    </AppShellContent>
  );
}
