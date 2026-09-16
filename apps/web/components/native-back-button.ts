"use client";

import { useEffect } from "react";
import { App } from "@capacitor/app";
import { isNativeShell } from "./native-runtime";
import { dismissTopmost } from "./dismissal-stack";
import { canNavigateBack } from "./native-history-depth";

/**
 * Android hardware/gesture Back integration (iOS has no equivalent hardware
 * key or `backButton` event — Capacitor only ever fires it on Android, see
 * @capacitor/app's own definitions.d.ts — so this hook is a harmless no-op
 * there and iOS behaviour is completely unchanged by it).
 *
 * Root cause this fixes: nothing in this app ever called
 * `App.addListener('backButton', ...)`. Capacitor's own docs are explicit
 * that registering this listener is required — "Listening for this event
 * will disable the default back button behaviour, so you might want to
 * call `window.history.back()` manually" — there is no automatic
 * history-back/exit fallback built in. With no listener at all, pressing
 * Back was simply swallowed: verified on-device that `history.back()`
 * called directly from JS navigated correctly, while the hardware/gesture
 * Back action did nothing at all, on every screen including an open
 * BottomSheet.
 *
 * Deliberately does not trust the `backButton` event's own `canGoBack`
 * field — confirmed on-device that it's the wrong signal for this app.
 * It reflects Android's *native* `WebView.canGoBack()`, which only tracks
 * full page loads; this app's whole router navigates via `pushState`
 * (a `<Link>`/`router.push()`), which never touches that native list, so
 * the field read `false` on every secondary route and every Back press
 * minimized the app instead of navigating. See native-history-depth.ts for
 * the actual "is there an internal previous route" signal used instead.
 *
 * Still NOT a second navigation stack: step 3 below calls the browser's
 * own `window.history.back()`, the exact same history <Link>/router.push()
 * already maintains — native-history-depth.ts only counts how many pushes
 * are ahead of the app's starting point, it never records *where* they go.
 */
function isEditableElement(element: Element | null): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) return true;
  // `isContentEditable` is the spec-correct check (and what real WebKit/
  // Blink report), but jsdom's test environment never implements it — it
  // reads `getAttribute` directly instead, so this also covers that.
  return element.isContentEditable || element.getAttribute("contenteditable") === "true";
}

export function useNativeBackButton(): void {
  useEffect(() => {
    if (!isNativeShell()) return;
    let disposed = false;
    let removeListener: (() => void) | undefined;

    void App.addListener("backButton", () => {
      // 1. Dismiss the keyboard first. Android's IME normally consumes the
      // hardware/gesture Back press itself while a native EditText is
      // focused, before the app ever sees it — but a WebView's own
      // <input>/<textarea> focus doesn't always get the same treatment
      // from every IME, so this is a deliberate, explicit safety net: never
      // let a Back press fall through to navigation/exit while a field is
      // still focused and the keyboard is (or may be) still showing.
      const active = document.activeElement;
      if (isEditableElement(active)) {
        active.blur();
        return;
      }
      // 2. Close the topmost open BottomSheet/modal instead of navigating
      // away — every sheet in the app registers itself via
      // dismissal-stack.ts for exactly this.
      if (dismissTopmost()) return;
      // 3. Ordinary back navigation, via the same browser history
      // <Link>/router.push() already maintains — Next.js's App Router
      // listens for the resulting popstate itself, so this is the entire
      // integration.
      if (canNavigateBack()) {
        window.history.back();
        return;
      }
      // 4. True root of the WebView's history: minimize like any other
      // Android app (moveTaskToBack) rather than exitApp() — a Back press
      // at the root is "go home," not "quit."
      void App.minimizeApp();
    }).then((handle) => {
      if (disposed) void handle.remove();
      else removeListener = () => void handle.remove();
    });

    return () => {
      disposed = true;
      removeListener?.();
    };
  }, []);
}

/** Mounted once, at the true app root (see app/layout.tsx, alongside
 *  ServiceWorkerRegister) — regardless of route, including the public
 *  marketing/login/onboarding pages that render no AppShell, since Back
 *  must work correctly there too. Renders nothing. */
export function NativeBackButton() {
  useNativeBackButton();
  return null;
}
