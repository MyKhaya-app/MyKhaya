"use client";

import { FormEvent, ReactNode, useEffect, useId, useRef } from "react";

/**
 * Base dialog primitive. Replaces the hand-rolled
 * `.platform-modal-backdrop > .platform-modal` markup duplicated per page.
 * Manages initial focus (first focusable element, or the dialog itself) on
 * open and returns focus to whatever triggered it on close — the existing
 * modals didn't manage focus at all, so this is an accessibility
 * improvement on top of the existing Escape/backdrop-click-to-close
 * behaviour, not a change to it.
 */
export function CcDialog({
  open,
  onClose,
  title,
  children,
  labelledBy,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  labelledBy?: string;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const generatedId = useId();
  const titleId = labelledBy ?? `cc-dialog-title-${generatedId}`;

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const node = dialogRef.current;
    const focusable = node?.querySelector<HTMLElement>(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    (focusable ?? node)?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="platform-modal-backdrop cc-dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="platform-modal cc-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function CcDialogActions({ children }: { children: ReactNode }) {
  return <div className="platform-modal-actions">{children}</div>;
}

/**
 * The recurring "confirm with a reason" pattern used across every audited
 * Control Centre mutation (grant/revoke/reconcile, and the same shape
 * elsewhere): a required free-text reason (>= 10 chars) plus a Cancel /
 * Confirm pair. `variant="destructive"` visually and semantically separates
 * high-impact/irreversible actions (e.g. removing complimentary access)
 * from ordinary ones — it changes styling only, never what triggers the
 * action or what payload it sends (`reason`/`confirmed` stay identical to
 * before).
 */
export function CcConfirmDialog({
  open,
  onClose,
  title,
  description,
  extraFields,
  confirmLabel,
  variant = "default",
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  extraFields?: ReactNode;
  confirmLabel: string;
  variant?: "default" | "destructive";
  onConfirm: (formData: FormData) => void | Promise<void>;
}) {
  return (
    <CcDialog open={open} onClose={onClose} title={title}>
      {description && <p>{description}</p>}
      <form
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          void onConfirm(new FormData(event.currentTarget));
        }}
      >
        {extraFields}
        <label>
          Reason for this administrative action (at least 10 characters)
          <input name="audit_reason" type="text" required minLength={10} maxLength={500} />
        </label>
        <CcDialogActions>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={variant === "destructive" ? "danger" : undefined}>
            {confirmLabel}
          </button>
        </CcDialogActions>
      </form>
    </CcDialog>
  );
}
