"use client";

import { useEffect, useState } from "react";
import type { VehicleLookupResult } from "@mykhaya/shared-types";
import { AppShellContent } from "@/components/app-shell";
import { VehicleReport } from "../../report/vehicle-report";
import { consumeLookupReportHandoff } from "../../lookup-handoff";
import { useActiveHome } from "@/components/use-active-home";

export default function LookupVehicleReportPage() {
  const [result, setResult] = useState<VehicleLookupResult | null>(null);
  const { activeHomeId } = useActiveHome();
  useEffect(() => setResult(consumeLookupReportHandoff()), []);
  if (!result) return <AppShellContent><main className="standard-page module-page drv-page"><p className="notice" role="status">This one-off report has expired. Run the lookup again to create a new report.</p></main></AppShellContent>;
  return <AppShellContent><VehicleReport source="lookup" format="essential" homeId={activeHomeId ?? ""} lookupResult={result} vehicle={result} mot={result.mot} /></AppShellContent>;
}
