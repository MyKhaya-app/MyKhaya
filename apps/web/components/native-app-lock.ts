import { App } from "@capacitor/app";

// Phase 6/11's lifecycle lock policy: "cold launch -> authenticate, long
// background period -> authenticate, short task switch -> no unnecessary
// prompt" — implemented as one pure, directly-testable decision function
// (shouldRequireUnlock) plus a thin stateful wrapper around
// @capacitor/app's appStateChange event that records when the app was last
// backgrounded. Deliberately one exported constant, not a timing scattered
// across call sites.
export const BIOMETRIC_LOCK_TIMEOUT_MS = 5 * 60_000;

/** Pure decision: given when the app was last sent to the background (or
 * `null` if this is a cold launch / it has never been backgrounded this
 * process), should the next foreground require re-authentication?
 * `null` always requires it — a cold launch is exactly the case Phase 3
 * already covers via bootstrapSession(), and this function's caller only
 * ever needs to ask the question for a *resume*, but treating `null` as
 * "yes" here too means a caller can't accidentally skip unlocking by
 * misusing this function before the first background/foreground cycle. */
export function shouldRequireUnlock(
  backgroundedAt: number | null,
  now: number = Date.now(),
  timeoutMs: number = BIOMETRIC_LOCK_TIMEOUT_MS,
): boolean {
  if (backgroundedAt === null) return true;
  return now - backgroundedAt >= timeoutMs;
}

let backgroundedAt: number | null = null;
let listenerAttached = false;

/** Starts tracking background/foreground transitions via @capacitor/app.
 * Safe to call more than once (e.g. across re-renders) — only the first
 * call actually attaches a listener. Call `wasBackgroundedLongEnoughToLock()`
 * from a foreground handler to decide whether to re-authenticate. */
export function startAppLockTracking(): void {
  if (listenerAttached) return;
  listenerAttached = true;
  void App.addListener("appStateChange", ({ isActive }) => {
    if (!isActive) backgroundedAt = Date.now();
  });
}

export function wasBackgroundedLongEnoughToLock(now: number = Date.now()): boolean {
  return shouldRequireUnlock(backgroundedAt, now);
}

/** Whether at least one background transition has actually been recorded
 *  since the last `markUnlocked()` (or since the app started, if that has
 *  never fired). A resume handler needs this *in addition to*
 *  `wasBackgroundedLongEnoughToLock()`: `shouldRequireUnlock(null, ...)`
 *  deliberately returns `true` for "no recorded timestamp," which is the
 *  right default for a caller asking "is it safe to skip auth" (Phase 3's
 *  own cold-launch bootstrapSession() case), but the *opposite* of what a
 *  resume listener wants — some platforms are known to fire an initial
 *  `appStateChange { isActive: true }` once during ordinary app startup,
 *  before any real backgrounding has ever happened, and that must never be
 *  misread as "backgrounded forever, lock now." Checking this first lets a
 *  resume handler treat "never actually backgrounded yet" as "nothing to
 *  do here" and leave cold-launch bootstrap entirely to its own existing
 *  code path. */
export function hasEverBeenBackgrounded(): boolean {
  return backgroundedAt !== null;
}

/** Called once unlock has actually happened (biometric success, or a fresh
 * login) so the *next* foreground starts its own clock rather than
 * immediately re-locking on the following short task switch. */
export function markUnlocked(): void {
  backgroundedAt = null;
}

export function resetAppLockTrackingForTesting(): void {
  backgroundedAt = null;
  listenerAttached = false;
}
