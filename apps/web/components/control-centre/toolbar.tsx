import type { ReactNode } from "react";

/**
 * Horizontal bar for a list page's search/filter/create-action controls.
 * Deliberately just a layout primitive (reusing the `.cc-toolbar` treatment
 * already defined for the Control Centre) — it renders only what it's
 * given, so a page with no search yet (most of them, today) doesn't have to
 * fake one just to place a "Create" button consistently.
 */
export function CcToolbar({ children }: { children: ReactNode }) {
  return <div className="cc-toolbar">{children}</div>;
}
