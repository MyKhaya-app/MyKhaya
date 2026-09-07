import type { ComponentType, ReactNode } from "react";

export type CcActionVariant = "primary" | "secondary" | "caution" | "destructive";

export type CcActionIcon = ComponentType<{ size?: number; strokeWidth?: number; "aria-hidden"?: boolean }>;

export type CcAction = {
  key?: string;
  label: ReactNode;
  onClick?: () => void;
  href?: string;
  variant?: CcActionVariant;
  disabled?: boolean;
  icon?: CcActionIcon;
  type?: "button" | "submit";
};

const variantClass: Record<CcActionVariant, string> = {
  primary: "cc-action cc-action-primary",
  secondary: "secondary cc-action cc-action-secondary",
  caution: "cc-action cc-action-caution",
  destructive: "danger cc-action cc-action-destructive",
};

/**
 * A row of actions with one consistent set of variants — `primary` (the
 * page's one emphasised action, `--cc-primary`), `secondary` (everything
 * routine), `caution` (reversible but attention-worthy, `--cc-warning`) and
 * `destructive` (irreversible, `--cc-danger-strong`) — replacing the ad hoc
 * mix of bare `<button>`/`<button className="secondary">`/`<button
 * className="danger">` groups scattered across detail pages. Renders an
 * `<a>` when `href` is given, a `<button>` otherwise.
 */
export function CcActionBar({ actions }: { actions: CcAction[] }) {
  return (
    <div className="cc-action-bar">
      {actions.map((action, index) => {
        const Icon = action.icon;
        const className = variantClass[action.variant ?? "secondary"];
        const content = (
          <>
            {Icon && <Icon aria-hidden size={16} strokeWidth={2} />}
            <span>{action.label}</span>
          </>
        );
        const key = action.key ?? index;
        if (action.href) {
          return (
            <a key={key} className={className} href={action.href}>
              {content}
            </a>
          );
        }
        return (
          <button
            key={key}
            type={action.type ?? "button"}
            className={className}
            disabled={action.disabled}
            onClick={action.onClick}
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}
