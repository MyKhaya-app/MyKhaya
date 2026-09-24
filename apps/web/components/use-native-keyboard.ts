"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { isNativeShell } from "./native-runtime";

const KEYBOARD_THRESHOLD = 120;

/**
 * Tracks the temporary visual-viewport reduction caused by the native
 * software keyboard. This is deliberately shell-level state: every native
 * form gets the same dock behavior, without page-specific keyboard hacks.
 */
export function useNativeKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    if (!isNativeShell()) return;

    const viewport = window.visualViewport;
    let baselineHeight = viewport?.height ?? window.innerHeight;

    const update = () => {
      const currentHeight = viewport?.height ?? window.innerHeight;
      if (currentHeight > baselineHeight) {
        baselineHeight = currentHeight;
        setOpen(false);
        return;
      }
      setOpen(baselineHeight - currentHeight > KEYBOARD_THRESHOLD);
    };

    viewport?.addEventListener("resize", update);
    window.addEventListener("resize", update);
    return () => {
      viewport?.removeEventListener("resize", update);
      window.removeEventListener("resize", update);
      setOpen(false);
    };
  }, [pathname]);

  return open;
}
