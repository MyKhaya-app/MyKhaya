import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, Info, XCircle } from "lucide-react";
import type { CcBadgeTone } from "./badge";

const toneIcon: Record<CcBadgeTone, typeof CheckCircle2> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
  neutral: HelpCircle,
};

export type CcStatusCardItem = {
  label: ReactNode;
  value: ReactNode;
};

/**
 * Prominent current-state card for detail pages — a large status headline
 * (icon + label, coloured by `tone`) plus a compact set of supporting
 * key/value lines and an optional explanatory blurb. Intended for the kind
 * of "is this thing on right now" summary a page like a Demo/Test Home's
 * Enabled/Disabled + Expiry + Access currently renders as a bare `<dl>`.
 */
export function CcStatusCard({
  tone = "neutral",
  status,
  description,
  items,
  icon,
  children,
}: {
  tone?: CcBadgeTone;
  status: ReactNode;
  description?: ReactNode;
  items?: CcStatusCardItem[];
  /** Overrides the tone's default icon — for states (e.g. "Disabled") where
   * the tone-derived icon (HelpCircle for neutral) doesn't read as clearly
   * as a state-specific one. */
  icon?: typeof CheckCircle2;
  children?: ReactNode;
}) {
  const Icon = icon ?? toneIcon[tone];
  return (
    <div className={`cc-status-card cc-status-card-${tone}`}>
      <div className="cc-status-card-headline">
        <Icon aria-hidden="true" size={18} strokeWidth={2} />
        <strong>{status}</strong>
      </div>
      {description && <p className="cc-status-card-description">{description}</p>}
      {items && items.length > 0 && (
        <dl className="cc-status-card-items">
          {items.map((item, index) => (
            <div key={index}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {children}
    </div>
  );
}
