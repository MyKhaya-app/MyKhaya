import type { ReactNode } from "react";

export function CcNotice({
  tone,
  children,
}: {
  tone: "error" | "success" | "warning";
  children: ReactNode;
}) {
  const isAlert = tone === "error";
  return (
    <p className={`notice ${tone} cc-notice`} role={isAlert ? "alert" : "status"}>
      {children}
    </p>
  );
}

/**
 * Standalone replacement for the hand-rolled `<p role="status">Loading…</p>`
 * repeated across ~15 Control Centre pages. `CcTable` renders the same
 * markup internally for its own loading state; this exists so pages that
 * aren't rendering a `CcTable` (e.g. while a whole detail payload is still
 * in flight) get the identical treatment without hand-rolling it.
 */
export function CcLoadingState({ label = "Loading…" }: { label?: ReactNode }) {
  return <p role="status">{label}</p>;
}

/**
 * Standalone replacement for the hand-rolled `<p className="quiet-state">…`
 * / `<p className="platform-empty">…` pattern used once a list/table has
 * loaded but has nothing to show.
 */
export function CcEmptyState({ children = "No results." }: { children?: ReactNode }) {
  return <p className="quiet-state cc-empty-state">{children}</p>;
}

/**
 * Standalone replacement for the hand-rolled `<p className="notice error"
 * role="alert">…</p>` pattern. Kept distinct from `CcNotice` (which also
 * covers success/warning) because most call sites only ever need the error
 * case and importing a single-purpose component reads clearer at the call
 * site than `<CcNotice tone="error">`.
 */
export function CcErrorState({ children }: { children: ReactNode }) {
  return (
    <p className="notice error cc-error-state" role="alert">
      {children}
    </p>
  );
}
