"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import type { RoutineScope, VehicleCreatePayload, VehicleLookupResult } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { DRIVEWAY_COUNTRIES } from "../countries";

const FUEL_TYPES = ["Petrol", "Diesel", "Electric", "Hybrid", "Plug-in hybrid", "LPG", "Other"];

function defaultNickname(make: string, model: string, registration: string): string {
  const makeModel = [make.trim(), model.trim()].filter(Boolean).join(" ");
  return makeModel || registration.trim() || "My vehicle";
}

export default function AddVehiclePage() {
  const router = useRouter();
  const { activeHomeId } = useActiveHome();
  const [scope, setScope] = useState<RoutineScope>("household");
  const [countryCode, setCountryCode] = useState("GB");
  const [registration, setRegistration] = useState("");
  const [lookup, setLookup] = useState<VehicleLookupResult | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [nickname, setNickname] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState("");
  const [fuelType, setFuelType] = useState("");
  const [colour, setColour] = useState("");
  const [firstRegistrationDate, setFirstRegistrationDate] = useState("");
  const [engineSize, setEngineSize] = useState("");
  const [vin, setVin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function findVehicle() {
    if (!activeHomeId || lookupBusy || !registration.trim()) return;
    setLookupBusy(true);
    setError("");
    try {
      const result = await api.lookupVehicle(activeHomeId, {
        country_code: countryCode,
        registration,
      });
      setLookup(result);
      if (!result.found) {
        setError(result.message ?? "We couldn't find that registration.");
        setManual(true);
      } else {
        setMake(result.make ?? "");
        setModel(result.model ?? "");
        setYear(result.year ? String(result.year) : "");
        setFuelType(result.fuel_type ?? "");
        setColour(result.colour ?? "");
        setEngineSize(result.engine_size ?? "");
        setFirstRegistrationDate(result.first_registration_date ?? "");
        setRegistration(result.registration ?? registration);
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "We can't check vehicle details right now.");
      setManual(true);
    } finally {
      setLookupBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || busy) return;
    if (!countryCode || !registration.trim()) {
      setError("Add a country and a registration to continue.");
      return;
    }
    setBusy(true);
    setError("");
    const body: VehicleCreatePayload = {
      nickname: nickname.trim() || defaultNickname(make, model, registration),
      scope,
      country_code: countryCode,
      registration: registration.trim(),
      make: make.trim() || null,
      model: model.trim() || null,
      colour: colour.trim() || null,
      year: year ? Number(year) : null,
      fuel_type: fuelType || null,
      engine_size: engineSize.trim() || null,
      first_registration_date: firstRegistrationDate || null,
      vin: vin.trim() || null,
    };
    try {
      const vehicle = await api.createVehicle(activeHomeId, body);
      router.push(`/driveway/${vehicle.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add this vehicle.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPage
      title="Add vehicle"
      description="Manually add a vehicle to Driveway. You can edit these details later."
      backLink={{ href: "/driveway", label: "Driveway" }}
    >
      <form className="card details driveway-form" onSubmit={submit} noValidate>
        <FormStatus error={error} />
        <label>
          Country / region
          <select value={countryCode} onChange={(event) => setCountryCode(event.target.value)} required>
            {DRIVEWAY_COUNTRIES.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name}
              </option>
            ))}
          </select>
        </label>

        {countryCode === "GB" && !manual && !lookup?.found && (
          <>
            <p className="muted">Pop in the registration and we’ll find the details for you.</p>
            <button className="button" type="button" onClick={() => void findVehicle()} disabled={lookupBusy || !registration.trim()}>
              {lookupBusy ? "Checking…" : "Find my vehicle"}
            </button>
            <button className="tertiary" type="button" onClick={() => setManual(true)}>Add manually</button>
          </>
        )}
        {countryCode !== "GB" && !manual && (
          <>
            <p className="muted">Automatic vehicle lookup isn’t available for this country yet, but you can still add it manually.</p>
            <button className="tertiary" type="button" onClick={() => setManual(true)}>Add manually</button>
          </>
        )}

        {lookup?.found && <div className="driveway-lookup-result" role="status">
          <span className="more-icon-tile blue" aria-hidden="true">🚗</span>
          <strong>{[lookup.make, lookup.model].filter(Boolean).join(" ") || lookup.registration}</strong>
          <span>{lookup.registration}</span>
          <span>{[lookup.year, lookup.fuel_type, lookup.colour].filter(Boolean).join(" · ")}</span>
          {lookup.capabilities.map((capability) => <small key={capability}>{capability === "inspection" ? "MOT information available" : "Tax information available"}</small>)}
        </div>}

        {(manual || lookup?.found) && <>
        <label>
          Registration / licence plate
          <input
            value={registration}
            onChange={(event) => setRegistration(event.target.value)}
            maxLength={20}
            required
            autoCapitalize="characters"
          />
        </label>

        <div className="driveway-form-section">
          <p className="eyebrow">Who is this for?</p>
          <div className="rr-segmented" role="tablist" aria-label="Vehicle scope">
            <button
              type="button"
              role="tab"
              aria-selected={scope === "personal"}
              className={`rr-segment${scope === "personal" ? " rr-segment-active" : ""}`}
              onClick={() => setScope("personal")}
            >
              Personal
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={scope === "household"}
              className={`rr-segment${scope === "household" ? " rr-segment-active" : ""}`}
              onClick={() => setScope("household")}
            >
              Household
            </button>
          </div>
        </div>

        <label>
          Nickname
          <input
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            maxLength={120}
            placeholder={defaultNickname(make, model, registration)}
          />
        </label>
        <label>
          Make
          <input value={make} onChange={(event) => setMake(event.target.value)} maxLength={80} />
        </label>
        <label>
          Model
          <input value={model} onChange={(event) => setModel(event.target.value)} maxLength={80} />
        </label>
        <label>
          Year
          <input
            type="number"
            inputMode="numeric"
            value={year}
            onChange={(event) => setYear(event.target.value)}
            min={1900}
            max={2200}
          />
        </label>
        <label>
          Fuel type
          <select value={fuelType} onChange={(event) => setFuelType(event.target.value)}>
            <option value="">Not set</option>
            {FUEL_TYPES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Colour
          <input value={colour} onChange={(event) => setColour(event.target.value)} maxLength={40} />
        </label>
        <label>
          First registration date
          <input
            type="date"
            value={firstRegistrationDate}
            onChange={(event) => setFirstRegistrationDate(event.target.value)}
          />
        </label>
        <label>
          Engine size
          <input value={engineSize} onChange={(event) => setEngineSize(event.target.value)} maxLength={20} />
        </label>
        <label>
          VIN / chassis number
          <input value={vin} onChange={(event) => setVin(event.target.value)} maxLength={32} />
        </label>
        <small>Your VIN is only ever shown to you and your Home Admin.</small>

        <button className="button" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add vehicle"}
        </button>
        </>}
      </form>
    </SettingsPage>
  );
}
