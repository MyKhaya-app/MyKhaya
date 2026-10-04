"use client";

import { useEffect, useState } from "react";
import { isNativeShell } from "./native-runtime";

// Mirrors the canonical browser desktop/tablet shell breakpoint — the same
// `@media (min-width: 760px)` block in app/styles.css that reveals the left
// navigation rail and the persistent Around the House dock (see
// AroundHouseDock, mounted by AppShell only when `!isNativeShell()`). There
// is no shared CSS/JS breakpoint constant to import from in this codebase,
// so this literal and that media query must be kept in sync by hand if the
// breakpoint ever changes — same as the rail's own 224px width already
// being duplicated between CSS rules for the same reason.
const DESKTOP_SHELL_MIN_WIDTH = 760;

/**
 * True exactly when the browser desktop/tablet shell — left rail, persistent
 * Around the House dock, wide-screen composition — is the active
 * presentation. Always false inside the native shell (matching
 * AroundHouseDock's own gate) and false on the server/before mount, so a
 * component using this to decide between two mutually-exclusive surfaces
 * (e.g. Home's Around the House card vs. the desktop dock) defaults to the
 * mobile/native presentation until the real viewport is known.
 */
export function useDesktopShellActive(): boolean {
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (isNativeShell()) {
      setActive(false);
      return;
    }
    const query = window.matchMedia(`(min-width: ${DESKTOP_SHELL_MIN_WIDTH}px)`);
    const update = () => setActive(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return active;
}
