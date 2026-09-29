"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Member, VehicleCreatePayload, VehicleLookupResult } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { DRIVEWAY_COUNTRIES } from "../countries";

const FUEL_TYPES = ["Petrol", "Diesel", "Electric", "Hybrid", "Plug-in hybrid", "LPG", "Other"];

function defaultNickname(make: string, model: string, registration: string): string {
  const makeModel = [make.trim(), model.trim()].filter(Boolean).join(" ");
  return makeModel || registration.trim() || "My vehicle";
}

function normaliseRegistration(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, " ");
}

export default function AddVehiclePage() {
  const router = useRouter();
  const { activeHomeId } = useActiveHome();
  const { user } = useAuth();
  const [countryCode, setCountryCode] = useState("GB");
  const [members, setMembers] = useState<Member[]>([]);
  const [ownerUserId, setOwnerUserId] = useState(user?.id ?? "");
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

  useEffect(() => {
    if (!activeHomeId) return;
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId]);

  useEffect(() => {
    if (user?.id && !ownerUserId) setOwnerUserId(user.id);
  }, [ownerUserId, user?.id]);

  async function findVehicle() {
    const normalizedRegistration = normaliseRegistration(registration);
    if (!activeHomeId || lookupBusy || !normalizedRegistration) return;
    setLookupBusy(true);
    setError("");
    try {
      const result = await api.lookupVehicle(activeHomeId, {
        country_code: countryCode,
        registration: normalizedRegistration,
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
        setRegistration(result.registration ?? normalizedRegistration);
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
    const normalizedRegistration = normaliseRegistration(registration);
    if (!countryCode || !normalizedRegistration || !ownerUserId) {
      setError("Add a country and a registration to continue.");
      return;
    }
    setBusy(true);
    setError("");
    const body: VehicleCreatePayload = {
      nickname: nickname.trim() || defaultNickname(make, model, normalizedRegistration),
      owner_user_id: ownerUserId,
      country_code: countryCode,
      registration: normalizedRegistration,
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

        {(countryCode === "GB" || manual || lookup?.found) && (
          <label>
            Registration / licence plate
            <input
              value={registration}
              onChange={(event) => setRegistration(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && countryCode === "GB" && !manual && !lookup?.found) {
                  event.preventDefault();
                  void findVehicle();
                }
              }}
              maxLength={20}
              required
              autoCapitalize="characters"
            />
          </label>
        )}

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
          Owner
          <select value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)} required>
            {(members.length ? members : user ? [{ user_id: user.id, display_name: "You" } as Member] : []).map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.user_id === user?.id ? "You" : member.display_name}
              </option>
            ))}
          </select>
        </label>

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
