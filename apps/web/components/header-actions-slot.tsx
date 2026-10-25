"use client";

import { createContext, useContext } from "react";

/**
 * Where a page offers AppHeader's notifications/profile pill a place in its
 * own content, so the pill scrolls with that content instead of staying fixed
 * over it. Only the unfolded iPhone Duo's Home uses it (AppShell decides);
 * everywhere else the pill stays in the header and the slot stays empty.
 */
const HeaderActionsSlotContext = createContext<((element: HTMLElement | null) => void) | null>(null);

export const HeaderActionsSlotProvider = HeaderActionsSlotContext.Provider;

export function HeaderActionsSlot({ className }: { className: string }) {
  const register = useContext(HeaderActionsSlotContext);
  return <div className={className} ref={register ?? undefined} />;
}
