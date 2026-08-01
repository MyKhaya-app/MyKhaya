"use client";

import { useEffect, useRef } from "react";

export function BottomSheet({
  title,
  onDismiss,
  children,
  fullHeight = false,
}: {
  title: string;
  onDismiss: () => void;
  children: React.ReactNode;
  fullHeight?: boolean;
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
    const initialFocus = element?.querySelector<HTMLElement>(
      ".sheet-content input:not([disabled]), .sheet-content select:not([disabled]), .sheet-content textarea:not([disabled]), .sheet-content button:not([disabled])",
    );
    (initialFocus ?? element)?.focus();
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
          <button
            className="icon-button secondary"
            type="button"
            onClick={onDismiss}
            aria-label="Close dialog"
          >
            ×
          </button>
        </header>
        <div className="sheet-content">{children}</div>
      </div>
    </div>
  );
}
