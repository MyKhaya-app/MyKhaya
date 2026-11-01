"use client";

import type { WishlistOccasion } from "@mykhaya/shared-types";
import { FormField, FormRow } from "@/components/form-layout";
import type { FormFieldErrors, FormFieldMessages } from "@/components/form-field-errors";
import { WISHLIST_OCCASION_OPTIONS } from "./occasion";

// The wishlist fields shared by New wishlist (app/wish-lists) and Edit
// wishlist (app/wish-lists/[id]), on the shared form primitives
// (docs/design/forms.md). Each sheet keeps its own state, payload and save;
// this renders the fields.

export type WishlistFieldValues = {
  title: string;
  occasion: WishlistOccasion;
  occasionDate: string;
  description: string;
};

export const WISHLIST_FIELD_MESSAGES: FormFieldMessages = {
  title: { missing: "Give this wishlist a title.", blank: "Give this wishlist a title." },
};

export function WishlistFields({
  values,
  errors,
  onChange,
  autoFocusTitle = false,
}: {
  values: WishlistFieldValues;
  errors: FormFieldErrors;
  onChange: (patch: Partial<WishlistFieldValues>, field: keyof WishlistFieldValues) => void;
  autoFocusTitle?: boolean;
}) {
  return (
    <>
      <FormField label="Title" error={errors.title}>
        {(control) => (
          <input
            {...control}
            name="title"
            value={values.title}
            onChange={(event) => onChange({ title: event.target.value }, "title")}
            placeholder="e.g. Birthday wishlist"
            maxLength={160}
            autoFocus={autoFocusTitle}
            required
          />
        )}
      </FormField>
      <FormRow minColumnWidth="10rem">
        <FormField label="Occasion">
          {(control) => (
            <select {...control} value={values.occasion} onChange={(event) => onChange({ occasion: event.target.value as WishlistOccasion }, "occasion")}>
              {WISHLIST_OCCASION_OPTIONS.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          )}
        </FormField>
        <FormField label="Date (optional)" error={errors.occasionDate}>
          {(control) => (
            <input
              {...control}
              name="occasionDate"
              type="date"
              value={values.occasionDate}
              onChange={(event) => onChange({ occasionDate: event.target.value }, "occasionDate")}
            />
          )}
        </FormField>
      </FormRow>
      <FormField label="Description (optional)">
        {(control) => (
          <input {...control} value={values.description} onChange={(event) => onChange({ description: event.target.value }, "description")} maxLength={1000} />
        )}
      </FormField>
    </>
  );
}
