"use client";

import { useEffect, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import type { Member } from "@mykhaya/shared-types";
import { FormField, FormRow } from "@/components/form-layout";
import { DRIVEWAY_COUNTRIES } from "./countries";

// The vehicle fields shared by Add vehicle (app/driveway/add) and Edit
// details (app/driveway/[vehicleId]/details), on the shared form primitives
// (docs/design/forms.md). Each page keeps its own state, registration
// normalisation, payload, lookup flow and navigation; this renders the fields.

export const FUEL_TYPES = ["Petrol", "Diesel", "Electric", "Hybrid", "Plug-in hybrid", "LPG", "Other"];

export type VehicleFieldValues = {
  countryCode: string;
  registration: string;
  ownerUserId: string;
  nickname: string;
  make: string;
  model: string;
  year: string;
  fuelType: string;
  colour: string;
  firstRegistrationDate: string;
  engineSize: string;
  vin: string;
};

export type VehicleFieldName = "countryCode" | "registration" | "ownerUserId" | "nickname" | "year" | "firstRegistrationDate";
export type VehicleFieldErrors = Partial<Record<VehicleFieldName, string>>;

/**
 * The checks both pages make before saving, mirroring the API's vehicle
 * contract (VehicleCreate in apps/api/mykhaya/driveway_schemas.py): country
 * and owner are required, the year is 1900–2200, and a date the browser
 * could not read is not sent as "no date". `required` adds the page's own
 * required fields (registration always; nickname on Edit).
 */
export function vehicleFieldErrors(
  values: VehicleFieldValues,
  { requireNickname, firstRegistrationDateUnreadable }: { requireNickname: boolean; firstRegistrationDateUnreadable: boolean },
): VehicleFieldErrors {
  const errors: VehicleFieldErrors = {};
  if (!values.countryCode) errors.countryCode = "Choose the country or region the vehicle is registered in.";
  if (!values.registration.trim()) errors.registration = "Add the registration.";
  if (!values.ownerUserId) errors.ownerUserId = "Choose who the vehicle belongs to.";
  if (requireNickname && !values.nickname.trim()) errors.nickname = "Add a nickname.";
  if (values.year) {
    const year = Number(values.year);
    if (!Number.isInteger(year) || year < 1900 || year > 2200) errors.year = "Enter a year between 1900 and 2200.";
  }
  if (firstRegistrationDateUnreadable) errors.firstRegistrationDate = "Enter a full date, or clear it.";
  return errors;
}

/** True when a date input holds something the browser could not read as a date. */
export function dateInputUnreadable(form: HTMLFormElement, name: string): boolean {
  const input = form.elements.namedItem(name);
  return input instanceof HTMLInputElement && input.validity.badInput;
}

/**
 * After a submit that failed its own checks, moves focus to the first field
 * marked invalid, so its error is announced with it. `attempt` increases on
 * each failed submit.
 */
export function useFocusFirstInvalid(container: RefObject<HTMLElement | null>, attempt: number) {
  useEffect(() => {
    if (!attempt) return;
    container.current?.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid-focus="true"]')?.focus();
  }, [attempt, container]);
}

export function VehicleFields({
  values,
  onChange,
  errors,
  members,
  currentUserId,
  showRegistration = true,
  showDetails = true,
  showVin,
  nicknamePlaceholder,
  nicknameRequired = false,
  onRegistrationKeyDown,
  afterRegistration,
}: {
  values: VehicleFieldValues;
  onChange: (patch: Partial<VehicleFieldValues>) => void;
  errors: VehicleFieldErrors;
  members: Member[];
  currentUserId: string | undefined;
  /** Add vehicle shows Registration only once a lookup or manual entry applies. */
  showRegistration?: boolean;
  /** Add vehicle shows the remaining fields only after a lookup or "Add manually". */
  showDetails?: boolean;
  /** The VIN is only ever shown to the vehicle's owner and a Home Admin. */
  showVin: boolean;
  nicknamePlaceholder?: string;
  nicknameRequired?: boolean;
  onRegistrationKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  /** Rendered after Registration: Add vehicle's lookup actions and result. */
  afterRegistration?: ReactNode;
}) {
  const ownerOptions = members.length
    ? members
    : currentUserId
      ? [{ user_id: currentUserId, display_name: "You" } as Member]
      : [];
  return (
    <>
      <FormField label="Country / region" error={errors.countryCode}>
        {(control) => (
          <select {...control} value={values.countryCode} onChange={(event) => onChange({ countryCode: event.target.value })} required>
            {DRIVEWAY_COUNTRIES.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name}
              </option>
            ))}
          </select>
        )}
      </FormField>

      {showRegistration && (
        <FormField label="Registration / licence plate" error={errors.registration}>
          {(control) => (
            <input
              {...control}
              value={values.registration}
              onChange={(event) => onChange({ registration: event.target.value })}
              onKeyDown={onRegistrationKeyDown}
              maxLength={20}
              required
              autoCapitalize="characters"
            />
          )}
        </FormField>
      )}

      {afterRegistration}

      {showDetails && (
        <>
          <FormField label="Owner" error={errors.ownerUserId}>
            {(control) => (
              <select {...control} value={values.ownerUserId} onChange={(event) => onChange({ ownerUserId: event.target.value })} required>
                {ownerOptions.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.user_id === currentUserId ? "You" : member.display_name}
                  </option>
                ))}
              </select>
            )}
          </FormField>
          <FormField label="Nickname" error={errors.nickname}>
            {(control) => (
              <input
                {...control}
                value={values.nickname}
                onChange={(event) => onChange({ nickname: event.target.value })}
                maxLength={120}
                placeholder={nicknamePlaceholder}
                required={nicknameRequired}
              />
            )}
          </FormField>
          <FormRow>
            <FormField label="Make">
              {(control) => <input {...control} value={values.make} onChange={(event) => onChange({ make: event.target.value })} maxLength={80} />}
            </FormField>
            <FormField label="Model">
              {(control) => <input {...control} value={values.model} onChange={(event) => onChange({ model: event.target.value })} maxLength={80} />}
            </FormField>
          </FormRow>
          {/* Fuel type has long options ("Plug-in hybrid"): stack on phones. */}
          <FormRow minColumnWidth="14rem">
            <FormField label="Year" error={errors.year}>
              {(control) => (
                <input
                  {...control}
                  type="number"
                  inputMode="numeric"
                  value={values.year}
                  onChange={(event) => onChange({ year: event.target.value })}
                  min={1900}
                  max={2200}
                />
              )}
            </FormField>
            <FormField label="Fuel type">
              {(control) => (
                <select {...control} value={values.fuelType} onChange={(event) => onChange({ fuelType: event.target.value })}>
                  <option value="">Not set</option>
                  {FUEL_TYPES.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
          </FormRow>
          <FormRow>
            <FormField label="Colour">
              {(control) => <input {...control} value={values.colour} onChange={(event) => onChange({ colour: event.target.value })} maxLength={40} />}
            </FormField>
            <FormField label="Engine size">
              {(control) => <input {...control} value={values.engineSize} onChange={(event) => onChange({ engineSize: event.target.value })} maxLength={20} />}
            </FormField>
          </FormRow>
          <FormField label="First registration date" error={errors.firstRegistrationDate}>
            {(control) => (
              <input
                {...control}
                type="date"
                name="first_registration_date"
                value={values.firstRegistrationDate}
                onChange={(event) => onChange({ firstRegistrationDate: event.target.value })}
              />
            )}
          </FormField>
          {showVin && (
            <FormField label="VIN / chassis number" hint="Your VIN is only ever shown to you and your Home Admin.">
              {(control) => <input {...control} value={values.vin} onChange={(event) => onChange({ vin: event.target.value })} maxLength={32} />}
            </FormField>
          )}
        </>
      )}
    </>
  );
}
