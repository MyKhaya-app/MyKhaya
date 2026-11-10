"use client";

import type { ReactNode } from "react";
import { FormField } from "@/components/form-layout";

// Budget's forms on the shared form primitives (docs/design/forms.md). Field
// errors come from components/form-field-errors.ts, which reads each
// control's own constraints; the Budget names below are kept for its forms.

export {
  constraintError,
  formFieldErrors as budgetFieldErrors,
  useFormFieldErrors as useBudgetFieldErrors,
  type FormFieldErrors as BudgetFieldErrors,
  type FormFieldMessages as BudgetFieldMessages,
} from "@/components/form-field-errors";

/**
 * A money field: a number input with the field's existing minimum and two
 * decimal places, and no currency symbol inside it. The value stays the
 * string the person typed; each form converts it exactly as before.
 */
export function BudgetAmountField({
  label,
  name,
  value,
  onChange,
  error,
  min = "0",
  required = true,
  hint,
}: {
  label: ReactNode;
  name: string;
  value: string | number;
  onChange: (value: string) => void;
  error?: string;
  /** "0" for planned and income amounts, "0.01" for spending entries. */
  min?: "0" | "0.01";
  required?: boolean;
  hint?: ReactNode;
}) {
  return (
    <FormField label={label} error={error} hint={hint}>
      {(control) => (
        <input
          {...control}
          name={name}
          type="number"
          min={min}
          step="0.01"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required={required}
        />
      )}
    </FormField>
  );
}
