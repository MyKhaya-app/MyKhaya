"use client";

import { useEffect } from "react";
import type { User } from "@mykhaya/shared-types";

const EVENT = "mykhaya:user-updated";

/** Broadcasts a fresh User (e.g. after an avatar change) to every mounted AppShell in
 *  this tab, so the header updates immediately without a refetch or a hard refresh. */
export function emitUserUpdated(user: User) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<User>(EVENT, { detail: user }));
}

export function useUserUpdatedListener(onUpdate: (user: User) => void) {
  useEffect(() => {
    function handle(event: Event) {
      onUpdate((event as CustomEvent<User>).detail);
    }
    window.addEventListener(EVENT, handle);
    return () => window.removeEventListener(EVENT, handle);
  }, [onUpdate]);
}
