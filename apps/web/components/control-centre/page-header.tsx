import type { ReactNode } from "react";

/**
 * Consistent Control Centre page header: eyebrow, title, description,
 * metadata line, and two action tiers. `secondaryActions` (back links,
 * refresh) render as low-emphasis controls so they never visually compete
 * with `primaryAction` — which itself should never be the destructive
 * control for a page; destructive actions live in their own section, not
 * the header.
 */
export function CcPageHeader({
  eyebrow,
  title,
  description,
  meta,
  primaryAction,
  secondaryActions,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
}) {
  return (
    <header className="cc-page-header">
      <div className="cc-page-header-main">
        {eyebrow && <p className="cc-eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="cc-page-description">{description}</p>}
        {meta && <div className="cc-page-meta">{meta}</div>}
      </div>
      {(primaryAction || secondaryActions) && (
        <div className="cc-page-header-actions">
          {secondaryActions && <div className="cc-page-header-secondary">{secondaryActions}</div>}
          {primaryAction}
        </div>
      )}
    </header>
  );
}
