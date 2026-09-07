import type { ComponentType, ReactNode } from "react";

type CcCardIcon = ComponentType<{ size?: number; strokeWidth?: number; "aria-hidden"?: boolean }>;

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

/**
 * `title`/`description`/`icon`/`actions` are optional — when given, they
 * render as a header row *inside* the card (icon + heading, supporting
 * copy, right-aligned actions) with a divider before `children`, so a
 * card can carry its own heading instead of relying on a separate
 * `CcSection` title floating above it. Omit them (as most existing call
 * sites do) and `CcCard` behaves exactly as before.
 */
export function CcCard({
  children,
  className = "",
  title,
  description,
  icon: Icon,
  actions,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  description?: ReactNode;
  icon?: CcCardIcon;
  actions?: ReactNode;
}) {
  return (
    <div className={`cc-card ${className}`.trim()}>
      {(title || actions) && (
        <div className="cc-card-header">
          <div className="cc-card-header-text">
            <h2>
              {Icon && <Icon aria-hidden size={18} strokeWidth={2} />}
              <span>{title}</span>
            </h2>
            {description && <p className="cc-card-description">{description}</p>}
          </div>
          {actions && <div className="cc-card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
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
