"use client";

import { useRef, useState } from "react";
import { useFocusFirstInvalid } from "./form-layout";

// Field errors for forms on the shared form primitives (docs/design/forms.md).
// FormLayout forms are noValidate, so the browser's own bubbles do not appear,
// but every control keeps the required/min/max/step/type constraints it
// declares. The errors below are read from those same constraints, so the
// checks are exactly the ones the browser would make and nothing new is
// enforced. The API stays the authority.

export type FormFieldErrors = Partial<Record<string, string>>;
type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
/** Per-field wording, by the control's name. */
export type FormFieldMessages = Record<string, { missing?: string; range?: string; blank?: string }>;

function isControl(element: Element): element is Control {
  return element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement;
}

function twoDecimalStep(control: Control) {
  return control.getAttribute("step") === "0.01";
}

/** The message for one control's failed native constraint, if any. */
export function constraintError(control: Control, messages: FormFieldMessages[string] = {}): string | undefined {
  if (!control.willValidate) return undefined;
  const { validity } = control;
  const type = control instanceof HTMLInputElement ? control.type : "";
  if (validity.badInput) {
    if (type === "date") return control.required ? "Enter a full date." : "Enter a full date, or clear it.";
    if (type === "month") return control.required ? "Enter a full month." : "Enter a full month, or clear it.";
    if (type === "time") return control.required ? "Enter a full time." : "Enter a full time, or clear it.";
    return twoDecimalStep(control) ? "Enter an amount, like 12.50." : "Enter a whole number.";
  }
  if (validity.valueMissing) return messages.missing ?? "Fill in this field.";
  if (validity.typeMismatch) {
    if (type === "email") return "Enter an email address, like name@example.com.";
    if (type === "url") return "Enter a full link, starting with https://.";
  }
  if (validity.rangeUnderflow || validity.rangeOverflow) {
    if (messages.range) return messages.range;
    const min = control.getAttribute("min");
    const max = control.getAttribute("max");
    if (min && max) return `Enter a number from ${min} to ${max}.`;
    if (min === "0.01") return "Enter an amount greater than 0.";
    if (min) return `Enter ${min} or more.`;
    return `Enter ${max} or less.`;
  }
  if (validity.stepMismatch) return twoDecimalStep(control) ? "Use no more than 2 decimal places." : "Enter a whole number.";
  if (!validity.valid) return control.validationMessage || "Check this field.";
  return undefined;
}

/**
 * Errors for every named control in the form, from its own constraints.
 * `blank` additionally rejects a value that is only spaces, for fields the
 * form already trims before saving (the API would reject the empty name).
 */
export function formFieldErrors(form: HTMLFormElement, messages: FormFieldMessages = {}): FormFieldErrors {
  const errors: FormFieldErrors = {};
  for (const element of Array.from(form.elements)) {
    if (!isControl(element) || !element.name || errors[element.name]) continue;
    const fieldMessages = messages[element.name];
    const error = constraintError(element, fieldMessages)
      ?? (fieldMessages?.blank && element.value.length > 0 && !element.value.trim() ? fieldMessages.blank : undefined);
    if (error) errors[element.name] = error;
  }
  return errors;
}

/**
 * Field errors for one form: `check` runs on submit and returns whether the
 * form may save; after a failed check, focus moves to the first invalid
 * control. `clear` drops one field's error when it is edited, and
 * `clearAll` every error.
 */
export function useFormFieldErrors(messages: FormFieldMessages) {
  const formRef = useRef<HTMLFormElement>(null);
  const [errors, setErrors] = useState<FormFieldErrors>({});
  const [failedAttempts, setFailedAttempts] = useState(0);
  useFocusFirstInvalid(formRef, failedAttempts);
  function check() {
    const next = formRef.current ? formFieldErrors(formRef.current, messages) : {};
    setErrors(next);
    const valid = Object.keys(next).length === 0;
    if (!valid) setFailedAttempts((count) => count + 1);
    return valid;
  }
  function clear(name: string) {
    setErrors((current) => (current[name] ? { ...current, [name]: undefined } : current));
  }
  /** Drops every error, for a form that is reopened with new values. */
  function clearAll() {
    setErrors({});
  }
  return { formRef, errors, check, clear, clearAll };
}
