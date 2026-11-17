"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import type { VehicleLookupResult } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormActions, FormField, FormLayout } from "@/components/form-layout";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { checkedAgo, formatRegistrationDate, formatShortDate } from "../vehicle-display";
import { storeLookupHandoff } from "../lookup-handoff";

function normaliseRegistration(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, " ");
}

function Facts({ items }: { items: Array<[string, string | number | boolean | null | undefined]> }) {
  return <dl className="drv-lookup-facts">{items.map(([label, value]) => value !== null && value !== undefined && value !== "" ? <div key={label}><dt>{label}</dt><dd>{typeof value === "boolean" ? (value ? "Yes" : "No") : value}</dd></div> : null)}</dl>;
}

function LookupResult({ result, onAdd }: { result: VehicleLookupResult; onAdd: () => void }) {
  const mot = result.mot;
  return <div className="drv-lookup-result drv-card" role="status">
    <div className="drv-lookup-header"><div><p className="drv-eyebrow">Lookup result</p><h2>{[result.make, result.model].filter(Boolean).join(" ") || "Vehicle details unavailable"}</h2></div><span className="drv-plate-chip">{result.registration}</span></div>
    <p className="drv-muted-small">Checked {checkedAgo(result.checked_at) ?? "just now"}</p>
    <section className="drv-lookup-section"><h3>Vehicle details</h3><Facts items={[["Registration", result.registration], ["Make", result.make], ["Model", result.model], ["Manufactured", result.year], ["First registration", formatRegistrationDate(result.first_registration_date, result.first_registration_precision)], ["First registered with DVLA", formatRegistrationDate(result.first_registration_with_dvla_date, result.first_registration_with_dvla_precision)], ["Fuel", result.fuel_type], ["Colour", result.colour], ["Engine capacity", result.engine_size ? `${result.engine_size} cc` : null]]} /></section>
    <section className="drv-lookup-section"><h3>Tax and status</h3><Facts items={[["Tax status", result.tax_status], ["Tax due", formatRegistrationDate(result.tax_due_date, "day")], ["SORN / vehicle status", result.vehicle_status], ["Additional-rate end", formatRegistrationDate(result.art_end_date, "day")], ["Marked for export", result.marked_for_export], ["Marked as scrapped", result.marked_as_scrapped]]} /></section>
    <section className="drv-lookup-section"><h3>Additional vehicle details</h3><Facts items={[["CO₂", result.co2_emissions !== null ? `${result.co2_emissions} g/km` : null], ["Euro status", result.euro_status], ["Type approval", result.type_approval], ["Wheelplan", result.wheel_plan], ["Revenue weight", result.revenue_weight ? `${result.revenue_weight} kg` : null], ["Real Driving Emissions", result.real_driving_emissions], ["Last V5C issued", formatRegistrationDate(result.date_of_last_v5c_issued, "day")], ["Automated vehicle", result.automated_vehicle]]} /></section>
    <section className="drv-lookup-section"><h3>MOT</h3>{mot ? <><Facts items={[["Status", mot.status], ["Due / expiry", formatRegistrationDate(mot.due_date, "day")], ["First MOT due", formatRegistrationDate(mot.first_mot_due_date, "day")]]} />{mot.tests.length > 0 ? <div className="drv-lookup-tests">{mot.tests.map((test, index) => <article className="drv-lookup-test" key={`${test.test_number ?? "test"}-${test.test_date}-${index}`}><strong>{formatShortDate(test.test_date) ?? test.test_date} · {test.result}</strong><span>{test.expiry_date ? `Expires ${formatShortDate(test.expiry_date)}` : "No expiry date"} · {test.odometer_value !== null ? `${test.odometer_value} ${test.odometer_unit ?? ""}` : "Mileage unavailable"}</span>{test.defects.length > 0 && <ul>{test.defects.map((defect, defectIndex) => <li key={`${defect.category}-${defectIndex}`}>{defect.dangerous ? "Dangerous: " : ""}{defect.text}</li>)}</ul>}</article>)}</div> : <p className="drv-muted">No detailed MOT tests were returned by the enabled provider.</p>}</> : <p className="drv-muted">Detailed MOT history is unavailable for this lookup. This does not confirm that the vehicle has no MOT defects.</p>}</section>
    <div className="drv-lookup-actions"><button className="drv-button drv-button-primary" type="button" onClick={onAdd}>Add to Driveway</button></div>
  </div>;
}

export default function VehicleLookupPage() {
  const router = useRouter();
  const { activeHomeId } = useActiveHome();
  const [registration, setRegistration] = useState("");
  const [result, setResult] = useState<VehicleLookupResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normaliseRegistration(registration);
    if (!activeHomeId || busy || !normalized) return;
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api.lookupVehicle(activeHomeId, { country_code: "GB", registration: normalized })); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "We couldn't check that vehicle right now."); }
    finally { setBusy(false); }
  }

  return <SettingsPage title="Vehicle lookup" description="Check a vehicle you might buy without saving it to Driveway." backLink={{ href: "/driveway", label: "Driveway" }}>
    <FormLayout className="card details" onSubmit={submit}><FormField label="Registration / licence plate">{(control) => <input {...control} value={registration} onChange={(event) => setRegistration(event.target.value)} autoCapitalize="characters" maxLength={20} required />}</FormField>{error && <p className="notice error" role="alert">{error}</p>}<FormActions><button className="button" type="submit" disabled={busy || !registration.trim()}>{busy ? "Checking…" : "Check vehicle"}</button></FormActions></FormLayout>
    {result?.found && <LookupResult result={result} onAdd={() => { storeLookupHandoff(result); router.push("/driveway/add"); }} />}
    {result && !result.found && <p className="notice" role="status">{result.message ?? "We couldn't find that registration."}</p>}
  </SettingsPage>;
}
