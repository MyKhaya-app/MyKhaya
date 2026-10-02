import { cloneElement, isValidElement, ReactNode, useId } from "react";

type FieldControlProps = {
  id?: string;
  "aria-describedby"?: string;
};

/**
 * Label + optional help text + error, with the label/input/help/error
 * association wired via `htmlFor`/`aria-describedby` so screen readers
 * announce help text and validation errors together with the field.
 * Expects a single form-control element as `children` (input/select/
 * textarea) and clones it with the id/aria-describedby needed to complete
 * that association, so call sites don't have to wire it up by hand.
 */
export function CcField({
  label,
  help,
  error,
  children,
  htmlFor,
}: {
  label: ReactNode;
  help?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  const generatedId = useId();
  const fieldId = htmlFor ?? generatedId;
  const helpId = help ? `${fieldId}-help` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;

  const control = isValidElement<FieldControlProps>(children)
    ? cloneElement(children, {
        id: fieldId,
        "aria-describedby": describedBy,
      })
    : children;

  return (
    <div className="cc-field">
      <label htmlFor={fieldId}>{label}</label>
      {help && (
        <p id={helpId} className="cc-field-help">
          {help}
        </p>
      )}
      {control}
      {error && (
        <p id={errorId} className="cc-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
