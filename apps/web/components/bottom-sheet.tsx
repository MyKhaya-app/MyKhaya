"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function BottomSheet({
  title,
  onDismiss,
  children,
  fullHeight = false,
  headerAction,
}: {
  title: string;
  onDismiss: () => void;
  children: React.ReactNode;
  fullHeight?: boolean;
  /** An optional action rendered between the title and the close button —
   *  e.g. the "Edit" action on a read-only event detail sheet. Kept generic
   *  (not calendar-specific) so any sheet can use it. */
  headerAction?: React.ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const dismiss = useRef(onDismiss);

  useEffect(() => {
    dismiss.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    restoreFocus.current = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    const scrollY = window.scrollY;
    const initialFocus = element?.querySelector<HTMLElement>(".bottom-sheet-close");
    // Focus the sheet control, never a form field. iOS Safari zooms when it
    // programmatically focuses a small input as a sheet opens.
    (initialFocus ?? element)?.focus();
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = "100%";
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss.current();
      if (event.key !== "Tab" || !element) return;
      const focusable = Array.from(
        element.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    document.body.classList.add("sheet-open");
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.classList.remove("sheet-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.width = "";
      window.scrollTo(0, scrollY);
      restoreFocus.current?.focus();
    };
  }, []);

  return (
    <div
      className="sheet-backdrop"
      onMouseDown={(event) =>
        event.target === event.currentTarget && onDismiss()
      }
    >
      <div
        className={`bottom-sheet ${fullHeight ? "full-height" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sheet-title"
        tabIndex={-1}
        ref={dialog}
      >
        <div className="sheet-handle" aria-hidden="true" />
        <header>
          <h2 id="sheet-title">{title}</h2>
          <div className="sheet-header-actions">
            {headerAction}
            <button
              className="icon-button secondary bottom-sheet-close"
              type="button"
              onClick={onDismiss}
              aria-label="Close dialog"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className="sheet-content">{children}</div>
      </div>
    </div>
  );
}
