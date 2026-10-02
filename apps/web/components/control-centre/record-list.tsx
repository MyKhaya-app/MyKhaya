import type { ReactNode } from "react";
import { CcBadge, type CcBadgeTone } from "./badge";
import { CcEmptyState } from "./status-message";

/**
 * One entry in a `CcRecordList` — generic enough to cover the memberships,
 * sessions, notes, activity and webhook-event lists duplicated as raw
 * `<div className="record-list"><article>…</article></div>` markup across
 * `homes/[id]`, `users/[id]` and `subscriptions/[id]`: a title, any number
 * of secondary meta lines, an optional badge, optional free-form body
 * content (e.g. a note's text, a timestamp), and optional actions.
 */
export function CcRecordCard({
  title,
  meta,
  badge,
  badgeTone = "neutral",
  actions,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode[];
  badge?: ReactNode;
  badgeTone?: CcBadgeTone;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className="cc-record-card">
      <div className="cc-record-card-main">
        <div className="cc-record-card-heading">
          <strong>{title}</strong>
          {badge && <CcBadge tone={badgeTone}>{badge}</CcBadge>}
        </div>
        {meta?.map((line, index) => (
          <span key={index}>{line}</span>
        ))}
        {children}
      </div>
      {actions && <div className="cc-record-card-actions">{actions}</div>}
    </article>
  );
}

/**
 * Wraps a set of `CcRecordCard`s in the existing `.record-list` container
 * treatment, and shows `emptyMessage` (via `CcEmptyState`) instead of an
 * empty box when there is nothing to list — replacing the
 * `list.length === 0 ? <p className="quiet-state">…</p> : <div
 * className="record-list">…</div>` conditional repeated at every call site.
 */
export function CcRecordList({
  children,
  emptyMessage = "No records yet.",
  variant = "list",
}: {
  children: ReactNode;
  emptyMessage?: ReactNode;
  /**
   * "list" (default): the original bordered single-column stack — right
   * for content whose body text benefits from full reading width (notes,
   * audit entries). "grid": a compact multi-column card grid for short,
   * uniform records (Home/session/passkey summaries) so they don't each
   * consume the full width of a wide desktop page for two lines of text.
   */
  variant?: "list" | "grid";
}) {
  const items = Array.isArray(children) ? children : [children];
  const hasItems = items.filter(Boolean).length > 0;
  if (!hasItems) {
    return <CcEmptyState>{emptyMessage}</CcEmptyState>;
  }
  return (
    <div className={variant === "grid" ? "cc-record-list-grid" : "record-list cc-record-list"}>
      {children}
    </div>
  );
}
