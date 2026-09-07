import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

/**
 * Card wrapper for destructive-only actions — reuses the existing
 * `.danger-zone` treatment (red-tinted border/background) already used
 * elsewhere in the Control Centre, plus a warning-triangle icon in the
 * heading, so a page's irreversible actions (delete, revoke, disable) are
 * visually set apart from routine ones. Meant to contain `CcActionBar`
 * (with `variant="destructive"` actions) and/or trigger a `CcConfirmDialog`.
 */
export function CcDangerZone({
  title = "Danger zone",
  description,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="danger-zone cc-danger-zone">
      <h2>
        <AlertTriangle aria-hidden="true" size={16} strokeWidth={2} />
        <span>{title}</span>
      </h2>
      {description && <p>{description}</p>}
      {children}
    </section>
  );
}
