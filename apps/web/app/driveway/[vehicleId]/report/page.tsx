"use client";

import { use, useEffect, useState } from "react";
import type { Vehicle, VehicleMot } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { VehiclePhoto } from "@/components/vehicle-photo";
import { useActiveHome } from "@/components/use-active-home";
import { VehicleReport, savedVehicleReportVehicle } from "../../report/vehicle-report";

export default function SavedVehicleReportPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [mot, setMot] = useState<VehicleMot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    let cancelled = false;
    void Promise.all([api.vehicle(activeHomeId, vehicleId), api.vehicleMot(activeHomeId, vehicleId)])
      .then(([nextVehicle, nextMot]) => { if (!cancelled) { setVehicle(nextVehicle); setMot(nextMot); } })
      .catch((cause) => { if (!cancelled) setError(cause instanceof ApiError ? cause.message : "This report could not be loaded."); });
    return () => { cancelled = true; };
  }, [activeHomeId, vehicleId]);

  if (!activeHomeId || !vehicle) return <AppShellContent><main className="standard-page module-page drv-page"><p className={error ? "notice error" : "empty-mini"} role={error ? "alert" : "status"}>{error || "Loading vehicle report…"}</p></main></AppShellContent>;
  return <AppShellContent><VehicleReport source="saved" format="full" homeId={activeHomeId} vehicleId={vehicle.id} vehicle={savedVehicleReportVehicle(vehicle)} taxCalculation={vehicle.tax_calculation} mot={mot} photo={<VehiclePhoto homeId={activeHomeId} vehicleId={vehicle.id} version={vehicle.photo_version} label={`${vehicle.make ?? "Vehicle"} photo`} />} /></AppShellContent>;
}
