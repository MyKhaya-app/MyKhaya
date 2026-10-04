/**
 * A tiny, ordered registry of "things that are currently open and should be
 * closed by a back action before anything else happens" — every
 * BottomSheet registers itself here for exactly the duration it's mounted
 * (see bottom-sheet.tsx). This is not a second navigation stack: nothing
 * here ever changes the URL or browser history, it only tracks which
 * overlay(s) are on screen right now so native-back-button.ts can close the
 * topmost one instead of navigating away or exiting the app.
 *
 * Deliberately a plain module-level array, not React state/context — every
 * consumer (native-back-button.ts, and BottomSheet itself) already reads it
 * imperatively from an event callback, never from a render, so there is
 * nothing for React to re-render in response to a push/pop here.
 */
const openDismissibles: Array<() => void> = [];

/** Call on mount; call the returned function on unmount. */
export function registerDismissible(dismiss: () => void): () => void {
  openDismissibles.push(dismiss);
  return () => {
    const index = openDismissibles.lastIndexOf(dismiss);
    if (index !== -1) openDismissibles.splice(index, 1);
  };
}

/** Closes the most-recently-opened dismissible, if any. Returns whether one
 *  was found and closed, so a caller (the back-button handler) knows
 *  whether it just consumed the back action or should fall through to its
 *  next step (history navigation). */
export function dismissTopmost(): boolean {
  const dismiss = openDismissibles.at(-1);
  if (!dismiss) return false;
  dismiss();
  return true;
}

/** Test-only: clears all registrations between tests. */
export function __resetDismissalStackForTesting(): void {
  openDismissibles.length = 0;
}
