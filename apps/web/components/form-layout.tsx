"use client";

import { useId, type FormEvent, type ReactNode } from "react";
import { BottomSheet } from "./bottom-sheet";

// Shared consumer form layout primitives. See docs/design/forms.md for when
// to use each one. The containment rules live in app/styles.css under
// "Shared form layout": every primitive is border-box, min-width: 0 and
// built on minmax(0, 1fr) tracks, so a control can never be wider than the
// container it sits in, including WebKit's native date/time controls.

/** Width-contained vertical stack of sections, rows and fields. */
export function FormLayout({
  children,
  className,
  id,
  onSubmit,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
  /** Renders a <form> when given; otherwise a plain <div>. */
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const classes = `form-layout${className ? ` ${className}` : ""}`;
  if (onSubmit) {
    return (
      <form id={id} className={classes} onSubmit={onSubmit} noValidate>
        {children}
      </form>
    );
  }
  return (
    <div id={id} className={classes}>
      {children}
    </div>
  );
}

/** A titled group of related fields: a <fieldset> with a <legend>. */
export function FormSection({
  title,
  children,
  actions,
  framed = false,
  divider = false,
  className,
}: {
  title: ReactNode;
  children: ReactNode;
  /** Section-level actions (e.g. "Remove destination"), after the fields. */
  actions?: ReactNode;
  /** A bordered card, for repeatable groups such as destination rows. */
  framed?: boolean;
  /** A rule above the section, for separating plain sections. */
  divider?: boolean;
  className?: string;
}) {
  const classes = [
    "form-section",
    framed ? "form-section-framed" : "",
    divider ? "form-section-divider" : "",
    className ?? "",
  ].filter(Boolean).join(" ");
  // The grid lives on an inner element rather than the <fieldset> itself:
  // WebKit has historically ignored display: grid/flex on fieldsets.
  return (
    <fieldset className={classes}>
      <legend className="form-section-title">{title}</legend>
      <div className="form-section-body">
        {children}
        {actions ? <div className="form-section-actions">{actions}</div> : null}
      </div>
    </fieldset>
  );
}

/**
 * Fields side by side. Columns never shrink below `minColumnWidth`; when the
 * container is too narrow for that, the row stacks to one column. This
 * responds to the space the row actually has (sheet, card, dialog or Duo
 * column), not to the viewport width.
 */
export function FormRow({
  children,
  columns = 2,
  minColumnWidth = "8.5rem",
  className,
}: {
  children: ReactNode;
  columns?: 1 | 2 | 3;
  minColumnWidth?: string;
  className?: string;
}) {
  return (
    <div
      className={`form-row${className ? ` ${className}` : ""}`}
      style={{ "--form-row-columns": columns, "--form-row-min": minColumnWidth } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

export type FormControlProps = {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
};

/**
 * Label, control, help text and error message for one control. The control
 * is rendered by `children`, which receives the id and ARIA wiring to spread
 * onto it, so the label and messages are always programmatically associated.
 */
export function FormField({
  label,
  hint,
  error,
  wide = false,
  className,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Span every column of the enclosing FormRow. */
  wide?: boolean;
  className?: string;
  children: (control: FormControlProps) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`form-field${wide ? " form-wide" : ""}${className ? ` ${className}` : ""}`}>
      <label className="form-field-label" htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, ...(error ? { "aria-invalid": true as const } : {}) })}
      {hint ? <p className="form-field-hint" id={hintId}>{hint}</p> : null}
      {error ? <p className="field-error form-field-error" id={errorId}>{error}</p> : null}
    </div>
  );
}

/** Primary then secondary actions, using the shared .sheet-actions row. */
export function FormActions({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`sheet-actions form-actions${className ? ` ${className}` : ""}`}>{children}</div>;
}

/**
 * A form presented in the shared BottomSheet with a pinned action footer.
 * The footer always carries a Cancel button as well as the header close
 * button: on devices where a system overlay can cover the header's top-right
 * corner (the iPhone Duo status indicator), dismissal must not depend on
 * that one control.
 */
export function FormSheet({
  title,
  onDismiss,
  primaryAction,
  cancelLabel = "Cancel",
  busy = false,
  fullHeight = false,
  children,
}: {
  title: string;
  onDismiss: () => void;
  /** The primary button, rendered first in the footer. */
  primaryAction: ReactNode;
  cancelLabel?: string;
  /** While busy, dismissal is ignored so an in-flight save is not orphaned. */
  busy?: boolean;
  fullHeight?: boolean;
  children: ReactNode;
}) {
  const dismiss = busy ? () => {} : onDismiss;
  return (
    <BottomSheet
      title={title}
      onDismiss={dismiss}
      fullHeight={fullHeight}
      footer={
        <FormActions>
          {primaryAction}
          <button type="button" className="secondary" onClick={dismiss} disabled={busy}>
            {cancelLabel}
          </button>
        </FormActions>
      }
    >
      {children}
    </BottomSheet>
  );
}
