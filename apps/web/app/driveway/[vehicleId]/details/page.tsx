"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, use, useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";
import type { RoutineScope, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { DRIVEWAY_COUNTRIES } from "../../countries";

const FUEL_TYPES = ["Petrol", "Diesel", "Electric", "Hybrid", "Plug-in hybrid", "LPG", "Other"];

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That vehicle could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function VehicleDetailsEditPage({
  params,
}: {
  params: Promise<{ vehicleId: string }>;
}) {
  const { vehicleId } = use(params);
  const router = useRouter();
  const { activeHomeId, activeHome } = useActiveHome();
  const { user } = useAuth();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [scope, setScope] = useState<RoutineScope>("household");
  const [countryCode, setCountryCode] = useState("GB");
  const [registration, setRegistration] = useState("");
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
    setNotFound(false);
    api
      .vehicle(activeHomeId, vehicleId)
      .then((row) => {
        setVehicle(row);
        setScope(row.scope);
        setCountryCode(row.country_code);
        setRegistration(row.registration ?? "");
        setNickname(row.nickname);
        setMake(row.make ?? "");
        setModel(row.model ?? "");
        setYear(row.year ? String(row.year) : "");
        setFuelType(row.fuel_type ?? "");
        setColour(row.colour ?? "");
        setFirstRegistrationDate(row.first_registration_date ?? "");
        setEngineSize(row.engine_size ?? "");
        setVin(row.vin ?? "");
      })
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
        else setLoadError(loadErrorMessage(cause, "Could not load this vehicle."));
      });
  }, [activeHomeId, vehicleId]);

  // A viewer who isn't this vehicle's own owner or a home_admin never
  // receives its VIN from the API (see routers.driveway) — the field is
  // left out of the form entirely for them rather than rendered blank,
  // which would otherwise look like (and risk becoming) clearing it.
  const canSeeVin =
    !!vehicle && !!user && (vehicle.owner_user_id === user.id || activeHome?.relationship === "home_admin");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || !vehicle || busy) return;
    if (!countryCode || !registration.trim() || !nickname.trim()) {
      setError("A nickname, country and registration are required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.updateVehicle(activeHomeId, vehicle.id, {
        nickname: nickname.trim(),
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
        vin: canSeeVin ? vin.trim() || null : null,
        expected_updated_at: vehicle.updated_at,
      });
      router.push(`/driveway/${vehicle.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save these changes.");
    } finally {
      setBusy(false);
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

  return (
    <AppShellContent>
      <main className="standard-page">
        <Link className="tertiary" href={`/driveway/${vehicle.id}`}>
          <ChevronLeft size={16} aria-hidden="true" /> {vehicle.nickname}
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Vehicle details</p>
            <h1>{vehicle.nickname}</h1>
          </div>
        </div>
        <FormStatus error={loadError} />

        <form className="card details driveway-form" onSubmit={submit} noValidate>
          <FormStatus error={error} />
          <label>
            Nickname
            <input
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              maxLength={120}
              required
            />
          </label>
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
          {canSeeVin && (
            <label>
              VIN / chassis number
              <input value={vin} onChange={(event) => setVin(event.target.value)} maxLength={32} />
            </label>
          )}

          <button className="button" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </form>
      </main>
    </AppShellContent>
  );
}
