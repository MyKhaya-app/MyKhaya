import type { ReactNode } from "react";

/**
 * Grouped-information card. `columns` renders `children` inside a
 * responsive grid (used for pairing e.g. the Home info card with the
 * Complimentary Access card) rather than stacking full-bleed sections down
 * a wide viewport.
 */
export function CcSection({
  title,
  description,
  actions,
  children,
  tone = "default",
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  tone?: "default" | "danger";
  className?: string;
}) {
  return (
    <section className={`cc-section ${tone === "danger" ? "cc-section-danger" : ""} ${className}`.trim()}>
      {(title || actions) && (
        <div className="cc-section-heading">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p className="cc-section-description">{description}</p>}
          </div>
          {actions && <div className="cc-section-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function CcCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`cc-card ${className}`.trim()}>{children}</div>;
}

export function CcColumns({
  children,
  ratio = "2-1",
}: {
  children: ReactNode;
  ratio?: "2-1" | "1-1";
}) {
  return <div className={`cc-columns cc-columns-${ratio}`}>{children}</div>;
}
