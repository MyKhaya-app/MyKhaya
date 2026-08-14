import type { ReactNode } from "react";

export type CcBadgeTone = "success" | "warning" | "danger" | "neutral" | "info";

export function CcBadge({ tone = "neutral", children }: { tone?: CcBadgeTone; children: ReactNode }) {
  return <strong className={`cc-badge cc-badge-${tone}`}>{children}</strong>;
}

/**
 * Adapter for the existing `state-label state-*` class strings produced by
 * `subscriptions-logic.ts` (planBadgeClass/statusBadgeClass/providerBadgeClass)
 * and similar helpers elsewhere, so those pure functions don't need to be
 * rewritten to know about the new tone system — they keep returning the
 * class name they always have, and this maps it to a CcBadge tone.
 */
export function toneFromStateClass(stateClass: string): CcBadgeTone {
  if (stateClass.includes("healthy")) return "success";
  if (
    stateClass.includes("warning") ||
    stateClass.includes("not-configured") ||
    stateClass.includes("queued")
  ) {
    return "warning";
  }
  if (
    stateClass.includes("degraded") ||
    stateClass.includes("unavailable") ||
    stateClass.includes("failed")
  ) {
    return "danger";
  }
  return "neutral";
}
