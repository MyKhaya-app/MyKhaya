/**
 * Answers "does the app have an internal previous route to go back to
 * right now?" — for native-back-button.ts's own use, since Capacitor's
 * `backButton` event's `canGoBack` field is the wrong signal for this SPA.
 *
 * That field reflects Android's *native* `WebView.canGoBack()` — its own
 * Java-level back-forward list of full page loads — not the DOM `history`
 * object. Confirmed on-device: navigating client-side from /home to
 * /settings (a plain `<Link>`, i.e. `history.pushState`, exactly how this
 * app's whole router works) leaves `window.history.length` at 2 as
 * expected, but the very next `backButton` event still reports
 * `canGoBack: false`, because no full WebView page load ever happened —
 * only a same-document pushState — so Android's native list never gained
 * an entry. Trusting that field made every secondary-route Back press
 * minimize the app instead of navigating to the previous route.
 *
 * `window.history.length` alone doesn't fix this either: per spec it's the
 * *size* of the whole session-history list, which back/forward navigation
 * never shrinks — it says nothing about the *current position* within it,
 * so it can't tell "one step from the start" apart from "several steps
 * in, having come back once already."
 *
 * This tracks that position directly instead — a plain depth counter, not
 * a second navigation stack: it never records *where* any entry points,
 * only *how many* pushState navigations are still "ahead of" the app's own
 * starting point, which is exactly the question a Back press needs
 * answered, and which the DOM's own APIs otherwise don't expose. Patching
 * `pushState` only to observe it (never to change what it does) is what
 * lets this stay accurate regardless of *how* something navigates —
 * `<Link>`, `router.push()`, or a future call site — without those call
 * sites needing to know this exists. `history.replaceState` (used by
 * router.replace(), e.g. redirects) is deliberately not counted: a
 * redirect must not leave the page it replaced as a Back target.
 */
let depth = 0;

// Installed once, as soon as this module is first imported — not lazily on
// first use — so a navigation that happens before anyone ever presses Back
// is still counted. native-back-button.ts imports this eagerly from
// NativeBackButton, mounted at the true app root (app/layout.tsx) before
// any route change can plausibly happen.
if (typeof window !== "undefined") {
  const originalPushState = window.history.pushState.bind(window.history);
  window.history.pushState = function patchedPushState(...args: Parameters<History["pushState"]>) {
    depth += 1;
    return originalPushState(...args);
  };
  window.addEventListener("popstate", () => {
    depth = Math.max(0, depth - 1);
  });
}

export function canNavigateBack(): boolean {
  return depth > 0;
}

/** Test-only: restores a clean starting depth between tests. */
export function __resetHistoryDepthForTesting(): void {
  depth = 0;
}
