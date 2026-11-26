"use client";

// Small presentation pieces shared by the Driveway screens. Styles live in
// styles.css under the scoped .drv-* selectors.
import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import type { VehicleLookupResult, VehicleMot } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { contrastText } from "@mykhaya/design-tokens";
import { memberColour } from "@/components/avatar";
import { FormActions, FormField, FormLayout } from "@/components/form-layout";
import { useActiveHome } from "@/components/use-active-home";
import { formatPlate, formatShortDate, initials, type MotTone } from "./vehicle-display";

/** UK number plate chip. */
export function PlateChip({ registration, size = "sm" }: { registration: string | null | undefined; size?: "sm" | "md" }) {
  const plate = formatPlate(registration);
  if (!plate) return null;
  return <span className={`drv-plate drv-plate-${size}`}>{plate}</span>;
}

/** MOT status pill. Words always carry the meaning; colour only reinforces it. */
export function MotPill({ tone, children, variant = "default" }: { tone: MotTone; children: string; variant?: "default" | "list" | "onGreen" }) {
  return <span className={`drv-pill drv-pill-${tone} drv-pill-${variant}`}>{children}</span>;
}

/** Owner initials in the member's own colour (never colour alone: initials
 *  plus an accessible name). */
export function OwnerAvatar({ userId, name, colour }: { userId: string; name: string; colour: string | null | undefined }) {
  // Same colour source and inline-style approach as components/avatar.tsx.
  const background = memberColour(userId, colour);
  return (
    <span className="drv-owner-avatar" role="img" aria-label={`Owner: ${name}`} title={name} style={{ background, color: contrastText(background) }}>
      {initials(name)}
    </span>
  );
}

/** The automatic freshness check plus a manual refresh for one vehicle's
 *  MOT. Reading never contacts the provider: an `if_stale` request lets the
 *  server decide; only the Refresh button forces a check. */
export function useMotRefresh(homeId: string | null, vehicleId: string, mot: VehicleMot | null, onChange: (next: VehicleMot) => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const autoChecked = useRef(false);
  const canRefresh = Boolean(mot?.eligible && mot.provider_available && mot.has_registration);
  const stale = mot?.summary.stale ?? false;

  useEffect(() => {
    if (!homeId || autoChecked.current || !canRefresh || !stale) return;
    autoChecked.current = true;
    api
      .refreshVehicleMot(homeId, vehicleId, "if_stale")
      .then(onChange)
      .catch(() => {
        // A background freshness check never interrupts the page.
      });
  }, [homeId, vehicleId, canRefresh, stale, onChange]);

  async function refresh() {
    if (!homeId || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const next = await api.refreshVehicleMot(homeId, vehicleId, "force");
      onChange(next);
      if (next.refresh?.message) setMessage(next.refresh.message);
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.message : "We couldn't check the MOT right now.");
    } finally {
      setBusy(false);
    }
  }

  return { canRefresh, busy, message, refresh };
}

export function RefreshButton({ busy, onClick, onGreen = false }: { busy: boolean; onClick: () => void; onGreen?: boolean }) {
  return (
    <button
      type="button"
      className={`drv-icon-button${onGreen ? " drv-icon-button-on-green" : ""}`}
      aria-label={busy ? "Checking MOT status" : "Refresh MOT status"}
      aria-busy={busy}
      disabled={busy}
      onClick={onClick}
    >
      <RefreshCw size={18} aria-hidden="true" className={busy ? "drv-spin" : undefined} />
    </button>
  );
}

export function VehicleLookupCard() {
  const { activeHomeId } = useActiveHome();
  const [registration, setRegistration] = useState("");
  const [result, setResult] = useState<VehicleLookupResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || busy || !registration.trim()) return;
    setBusy(true);
    setError("");
    try {
      setResult(await api.lookupVehicle(activeHomeId, { country_code: "GB", registration: registration.trim().toUpperCase() }));
    } catch (cause) {
      setResult(null);
      setError(cause instanceof ApiError ? cause.message : "We couldn't check that vehicle right now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="drv-lookup-card" aria-labelledby="drv-lookup-heading">
      <div className="drv-section-heading"><div><p className="drv-eyebrow">Considering a vehicle?</p><h2 id="drv-lookup-heading">Vehicle lookup</h2></div></div>
      <FormLayout className="details" onSubmit={submit}>
        <FormField label="Registration / licence plate">
          {(control) => <input {...control} value={registration} onChange={(event) => setRegistration(event.target.value)} autoCapitalize="characters" maxLength={20} required />}
        </FormField>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormActions><button className="button secondary" type="submit" disabled={busy || !registration.trim()}>{busy ? "Checking…" : "Check vehicle"}</button></FormActions>
      </FormLayout>
      {result?.found && (
        <div className="drv-card drv-lookup-result" role="status">
          <div className="drv-vehicle-meta"><PlateChip registration={result.registration} size="md" /><strong>{[result.make, result.model].filter(Boolean).join(" ") || "Vehicle details"}</strong></div>
          <p className="drv-muted-small">Checked {result.checked_at ? formatShortDate(result.checked_at) : "just now"}</p>
          <p className="drv-muted">{[result.year, result.fuel_type, result.colour].filter(Boolean).join(" · ") || "Some vehicle details are unavailable."}</p>
          <p className="drv-muted">{result.tax_status ? `Tax: ${result.tax_status}` : "Tax status unavailable"}{result.mot ? ` · MOT: ${result.mot.status ?? "unavailable"}` : " · MOT history unavailable"}</p>
          {result.mot?.tests.map((test) => <div className="drv-muted-small" key={`${test.test_number ?? "test"}-${test.test_date}`}><p>{formatShortDate(test.test_date)} · {test.result} · {test.odometer_value != null ? `${test.odometer_value} ${test.odometer_unit ?? ""}` : "mileage unavailable"}</p>{test.defects.map((defect, index) => <p key={`${test.test_number ?? test.test_date}-defect-${index}`}>{defect.dangerous ? "Dangerous: " : ""}{defect.text}</p>)}</div>)}
          <Link className="drv-button drv-button-primary" href={`/driveway/add?registration=${encodeURIComponent(result.registration ?? registration)}`}>Add to Driveway</Link>
        </div>
      )}
      {result && !result.found && <p className="notice" role="status">{result.message ?? "We couldn't find that registration."}</p>}
    </section>
  );
}

export function VehicleLookupEntryCard() {
  return (
    <section className="drv-lookup-card" aria-labelledby="drv-lookup-entry-heading">
      <div className="drv-section-heading"><div><p className="drv-eyebrow">Considering a vehicle?</p><h2 id="drv-lookup-entry-heading">Vehicle lookup</h2></div></div>
      <p className="drv-muted">Check a vehicle you might buy without adding it to your household vehicles.</p>
      <Link className="drv-button drv-button-secondary" href="/driveway/lookup">Open vehicle lookup</Link>
    </section>
  );
}
