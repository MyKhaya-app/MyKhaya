"use client";

import { useEffect } from "react";
import { isNativeShell } from "./native-runtime";

// Root-layout-mounted, so this covers every page for the whole app
// session — public/pre-auth routes included, unlike AppShell's own
// `.native-shell` class (components/app-shell.tsx), which is scoped to
// AppShell's mount lifecycle and therefore never present on /login,
// /login/child, /register, /calendar-shares/accept,
// /control-centre/accept-invitation, etc. That scoping is deliberate for
// AppShell's class — it drives the fixed-viewport single-scroll-region
// model (see styles.css's "Native shell viewport model"), which assumes
// AppShell's own header/bottom-nav structure and would break ordinary
// document scrolling on a page that has neither.
//
// This is a second, narrower class purely for safe-area padding — it
// never touches scrolling/viewport behaviour, so it's safe to apply
// everywhere, public pages included, without risk to AppShell's already
// road-tested layout. See the ".native-public-shell" rules in styles.css.
export function NativePublicShell() {
  useEffect(() => {
    if (!isNativeShell()) return;
    document.documentElement.classList.add("native-public-shell");
    return () => document.documentElement.classList.remove("native-public-shell");
  }, []);

  return null;
}
