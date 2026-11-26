"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Member, VehicleCreatePayload, VehicleLookupResult } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormActions, FormLayout } from "@/components/form-layout";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import {
  dateInputUnreadable,
  useFocusFirstInvalid,
  vehicleFieldErrors,
  VehicleFields,
  type VehicleFieldErrors,
  type VehicleFieldValues,
} from "../vehicle-fields";
import { consumeLookupHandoff } from "../lookup-handoff";
import { formatRegistrationDate } from "../vehicle-display";

// Never falls back to the registration: a nickname is shown and shared far
// more widely than the registration itself (lists, reminders, notifications),
// so defaulting it to the plate would copy a sensitive identifier into an
// unprotected field.
function defaultNickname(make: string, model: string): string {
  const makeModel = [make.trim(), model.trim()].filter(Boolean).join(" ");
  return makeModel || "My vehicle";
}

function normaliseRegistration(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, " ");
}

const EMPTY_VALUES: VehicleFieldValues = {
  countryCode: "GB",
  registration: "",
  ownerUserId: "",
  nickname: "",
  make: "",
  model: "",
  year: "",
  fuelType: "",
  colour: "",
  firstRegistrationDate: "",
  engineSize: "",
  vin: "",
};

export default function AddVehiclePage() {
  const router = useRouter();
  const { activeHomeId } = useActiveHome();
  const { user } = useAuth();
  const [values, setValues] = useState<VehicleFieldValues>({ ...EMPTY_VALUES, ownerUserId: user?.id ?? "" });
  const [members, setMembers] = useState<Member[]>([]);
  const [lookup, setLookup] = useState<VehicleLookupResult | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState("");
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<VehicleFieldErrors>({});
  const [failedAttempts, setFailedAttempts] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  useFocusFirstInvalid(formRef, failedAttempts);

  const { countryCode, registration, ownerUserId, make, model } = values;
  const update = (patch: Partial<VehicleFieldValues>) => {
    setValues((current) => ({ ...current, ...patch }));
    setFieldErrors((current) => {
      const next = { ...current };
      for (const key of Object.keys(patch)) delete next[key as keyof VehicleFieldErrors];
      return next;
    });
  };

  useEffect(() => {
    if (!activeHomeId) return;
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId]);

  // "Add a vehicle for {Name}" on the Driveway empty state links here with
  // ?owner=<user id>; only a real member of this Home is accepted.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("owner");
    const requestedRegistration = params.get("registration");
    const handoff = consumeLookupHandoff();
    if (requested && members.some((member) => member.user_id === requested)) {
      setValues((current) => ({ ...current, ownerUserId: requested }));
    }
    if (requestedRegistration) {
      setValues((current) => ({ ...current, registration: requestedRegistration }));
    }
    if (handoff?.found) {
      setLookup(handoff);
      setValues((current) => ({
        ...current,
        registration: handoff.registration ?? current.registration,
        make: handoff.make ?? "",
        model: handoff.model ?? "",
        year: handoff.year ? String(handoff.year) : "",
        fuelType: handoff.fuel_type ?? "",
        colour: handoff.colour ?? "",
        engineSize: handoff.engine_size ?? "",
        firstRegistrationDate: handoff.first_registration_date ?? "",
      }));
    }
  }, [members]);

  useEffect(() => {
    if (user?.id && !ownerUserId) setValues((current) => ({ ...current, ownerUserId: user.id }));
  }, [ownerUserId, user?.id]);

  async function findVehicle() {
    const normalizedRegistration = normaliseRegistration(registration);
    if (!activeHomeId || lookupBusy || !normalizedRegistration) return;
    setLookupBusy(true);
    setLookupError("");
    setError("");
    try {
      const result = await api.lookupVehicle(activeHomeId, {
        country_code: countryCode,
        registration: normalizedRegistration,
      });
      setLookup(result);
      if (!result.found) {
        setLookupError(result.message ?? "We couldn't find that registration.");
        setManual(true);
      } else {
        setValues((current) => ({
          ...current,
          make: result.make ?? "",
          model: result.model ?? "",
          year: result.year ? String(result.year) : "",
          fuelType: result.fuel_type ?? "",
          colour: result.colour ?? "",
          engineSize: result.engine_size ?? "",
          firstRegistrationDate: result.first_registration_date ?? "",
          registration: result.registration ?? normalizedRegistration,
        }));
      }
    } catch (cause) {
      setLookupError(cause instanceof ApiError ? cause.message : "We can't check vehicle details right now.");
      setManual(true);
    } finally {
      setLookupBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || busy) return;
    const normalizedRegistration = normaliseRegistration(registration);
    const errors = vehicleFieldErrors(
      { ...values, registration: normalizedRegistration },
      { requireNickname: false, firstRegistrationDateUnreadable: dateInputUnreadable(event.currentTarget, "first_registration_date") },
    );
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError("");
      setFailedAttempts((count) => count + 1);
      return;
    }
    setBusy(true);
    setError("");
    const body: VehicleCreatePayload = {
      nickname: values.nickname.trim() || defaultNickname(make, model),
      owner_user_id: ownerUserId,
      country_code: countryCode,
      registration: normalizedRegistration,
      make: make.trim() || null,
      model: model.trim() || null,
      colour: values.colour.trim() || null,
      year: values.year ? Number(values.year) : null,
      fuel_type: values.fuelType || null,
      engine_size: values.engineSize.trim() || null,
      first_registration_date: values.firstRegistrationDate || null,
      first_registration_precision: lookup?.first_registration_precision ?? (values.firstRegistrationDate ? "day" : null),
      vin: values.vin.trim() || null,
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

  const showDetails = manual || Boolean(lookup?.found);
  const legacyPreviewDisabled = false;

  return (
    <SettingsPage
      title="Add vehicle"
      description="Manually add a vehicle to Driveway. You can edit these details later."
      backLink={{ href: "/driveway", label: "Driveway" }}
    >
      <FormLayout className="card details vehicle-form" onSubmit={submit} ref={formRef}>
        <VehicleFields
          values={values}
          onChange={update}
          errors={fieldErrors}
          members={members}
          currentUserId={user?.id}
          showRegistration={countryCode === "GB" || showDetails}
          showDetails={showDetails}
          showVin
          nicknamePlaceholder={defaultNickname(make, model)}
          onRegistrationKeyDown={(event) => {
            if (event.key === "Enter" && countryCode === "GB" && !manual && !lookup?.found) {
              event.preventDefault();
              void findVehicle();
            }
          }}
          afterRegistration={
            <>
              {lookupError && <p className="notice error" role="alert">{lookupError}</p>}
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
                <div className="drv-lookup-section"><h3>Vehicle details</h3><dl className="drv-lookup-facts">
                  {[["Registration", lookup.registration], ["Make", lookup.make], ["Model", lookup.model], ["Year", lookup.year], ["Fuel", lookup.fuel_type], ["Colour", lookup.colour], ["Engine", lookup.engine_size ? `${lookup.engine_size} cc` : null], ["First registration", formatRegistrationDate(lookup.first_registration_date, lookup.first_registration_precision)]].map(([label, value]) => value ? <div key={label}><dt>{label}</dt><dd>{value}</dd></div> : null)}
                </dl></div>
                <div className="drv-lookup-section"><h3>Tax</h3><dl className="drv-lookup-facts">
                  {[['Status', lookup.tax_status], ['Due date', lookup.tax_due_date ? formatRegistrationDate(lookup.tax_due_date, "day") : null], ['Additional-rate end', lookup.art_end_date ? formatRegistrationDate(lookup.art_end_date, "day") : null], ['First registered with DVLA', formatRegistrationDate(lookup.first_registration_with_dvla_date, lookup.first_registration_with_dvla_precision)]].map(([label, value]) => value ? <div key={label}><dt>{label}</dt><dd>{value}</dd></div> : null)}
                </dl></div>
                {lookup.mot && <div className="drv-lookup-section"><h3>MOT</h3><p>{lookup.mot.status ?? "MOT information available"}{lookup.mot.due_date ? ` · due ${formatRegistrationDate(lookup.mot.due_date, "day")}` : ""}</p></div>}
                {lookup.capabilities.map((capability) => <p className="drv-muted-small" key={capability}>{capability === "inspection" ? "MOT information available" : capability === "tax" ? "Tax information available" : "Vehicle specifications available"}</p>)}
              </div>}
              {lookup?.found && legacyPreviewDisabled && <div className="driveway-lookup-result" role="status">
                <span className="more-icon-tile blue" aria-hidden="true">🚗</span>
                <strong>{[lookup.make, lookup.model].filter(Boolean).join(" ") || lookup.registration}</strong>
                <span>{lookup.registration}</span>
                <span>{lookup.engine_size ? `${lookup.engine_size} cc` : null}{lookup.tax_status ? ` · ${lookup.tax_status}` : ""}{lookup.mot?.status ? ` · MOT ${lookup.mot.status}` : ""}</span>
                {lookup.mot?.tests.slice(0, 3).map((test) => <small key={`${test.test_number ?? "test"}-${test.test_date}`}>{test.test_date} · {test.result} · {test.odometer_value != null ? `${test.odometer_value} ${test.odometer_unit ?? ""}` : "mileage unavailable"}</small>)}
                <span>{[lookup.year, lookup.fuel_type, lookup.colour].filter(Boolean).join(" · ")}</span>
                {lookup.capabilities.map((capability) => <small key={capability}>{capability === "inspection" ? "MOT information available" : "Tax information available"}</small>)}
              </div>}
            </>
          }
        />
        {showDetails && (
          <>
            {error && <p className="notice error" role="alert">{error}</p>}
            <FormActions>
              <button className="button" type="submit" disabled={busy}>
                {busy ? "Adding…" : "Add vehicle"}
              </button>
            </FormActions>
          </>
        )}
      </FormLayout>
    </SettingsPage>
  );
}
