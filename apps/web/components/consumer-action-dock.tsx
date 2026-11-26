"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, Plus } from "lucide-react";
import { dismissTopmost } from "./dismissal-stack";
import { canNavigateBack } from "./native-history-depth";
import { nativePlatform } from "./native-runtime";
import { consumerRouteMetadata } from "./consumer-route-metadata";

/** The only text the primary action button ever shows. */
export const PRIMARY_VISIBLE_LABEL = "Add";

export type ConsumerPrimaryAction = {
  /** Action-specific accessible name and tooltip, e.g. "Add vehicle". Never shown as visible text. */
  label: string;
  onActivate: () => void;
  href?: string;
  enabled?: boolean;
};

type ActionContextValue = {
  action: ConsumerPrimaryAction | null;
  setPrimaryAction: (action: ConsumerPrimaryAction | null) => void;
};

const ActionContext = createContext<ActionContextValue | null>(null);

export function ConsumerActionProvider({ children }: { children: React.ReactNode }) {
  const [primaryAction, setPrimaryAction] = useState<ConsumerPrimaryAction | null>(null);
  const value = useMemo(() => ({ action: primaryAction, setPrimaryAction }), [primaryAction]);
  return <ActionContext.Provider value={value}>{children}</ActionContext.Provider>;
}

/**
 * Registers the current module action with the shell's ConsumerActionDock.
 *
 * The action must be a stable reference: memoise it (useMemo, with every value
 * its label, enabled flag and callback read in the dependency list) so its
 * identity changes only when one of those changes. A new object on every render
 * re-runs this effect, which updates the provider, which re-renders the page,
 * which creates another object: an endless render loop.
 */
export function useConsumerPrimaryAction(action: ConsumerPrimaryAction | null): void {
  const context = useContext(ActionContext);
  useEffect(() => {
    if (!context) return;
    context.setPrimaryAction(action);
    return () => context.setPrimaryAction(null);
  }, [action, context]);
}

export function ConsumerActionDock() {
  const context = useContext(ActionContext);
  const action = context?.action ?? null;
  const pathname = usePathname();
  const router = useRouter();
  const metadata = consumerRouteMetadata(pathname);
  const platform = nativePlatform();
  const showNativeBack = platform === "ios" && Boolean(metadata.backFallback);
  const showPrimary = Boolean(action?.enabled ?? true);

  function goBack() {
    if (dismissTopmost()) return;
    if (canNavigateBack()) {
      window.history.back();
      return;
    }
    if (metadata.backFallback) router.replace(metadata.backFallback);
  }

  if (!showNativeBack && !(action && showPrimary)) return null;
  // One bottom action row across the content width: Back is always the
  // start (left) slot and the primary action always the end (right) slot,
  // whether or not the other is present. The visible label is always the
  // generic "Add"; the module's specific description (e.g. "Add vehicle")
  // stays the button's accessible name and tooltip. The iPhone Duo rail
  // restyles this same markup as icon-only rail controls in styles.css.
  return (
    <div className="consumer-action-dock" aria-label="Page actions">
      {showNativeBack && (
        <button type="button" className="consumer-action consumer-back-action" onClick={goBack} aria-label="Back">
          <ArrowLeft size={20} strokeWidth={2.25} aria-hidden="true" />
          <span>Back</span>
        </button>
      )}
      {action && showPrimary && (
        <button
          type="button"
          className="consumer-action consumer-primary-action"
          onClick={() => (action.href ? router.push(action.href) : action.onActivate())}
          aria-label={action.label}
          title={action.label}
        >
          <Plus size={21} strokeWidth={2.5} aria-hidden="true" />
          <span aria-hidden="true">{PRIMARY_VISIBLE_LABEL}</span>
        </button>
      )}
    </div>
  );
}
