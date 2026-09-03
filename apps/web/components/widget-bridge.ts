import { registerPlugin } from "@capacitor/core";
import { api } from "@mykhaya/api-client";
import { isNativeShell } from "./native-runtime";
import {
  type WidgetSnapshot,
  buildWidgetSnapshot,
  emptyHomeWidgetSnapshot,
  signedOutWidgetSnapshot,
} from "./widget-snapshot";

/**
 * TS-side contract for the native `WidgetBridgePlugin` (Swift source in
 * apps/ios-shell/native/plugin/WidgetBridgePlugin.swift, installed into the
 * generated ios/ project by scripts/install-widget-sources.sh — see
 * docs/mobile/ios-widgets.md). This is a repo-local plugin, not an npm
 * package: outside the real native shell (an ordinary browser tab, Vitest,
 * a native shell build where the plugin hasn't been installed yet)
 * Capacitor's web fallback throws "not implemented" for every method, which
 * is why every export below is guarded by `isNativeShell()` first.
 */
export interface WidgetBridgePlugin {
  /** Atomically replaces the shared App Group snapshot with `json` (the
   *  JSON-encoded WidgetSnapshot) and requests WidgetKit reload every
   *  MyKhaya widget timeline. */
  setSnapshot(options: { json: string }): Promise<void>;
  /** Replaces the snapshot with the signed-out state and reloads timelines
   *  — called on logout so no household data lingers on the Home Screen. */
  clearSnapshot(): Promise<void>;
}

const WidgetBridge = registerPlugin<WidgetBridgePlugin>("WidgetBridge");

let inFlight: Promise<void> | null = null;

async function writeSnapshot(snapshot: WidgetSnapshot): Promise<void> {
  if (!isNativeShell()) return;
  await WidgetBridge.setSnapshot({ json: JSON.stringify(snapshot) });
}

/**
 * Fetches the same authorised data the Calendar and Routines & Reminders
 * pages already fetch (via the shared `api` client — no separate widget
 * endpoint, no separate auth path), shapes it into a WidgetSnapshot, and
 * hands it to the native layer. No-ops outside the native shell.
 *
 * Callers: native-auth.ts (session restore / login / active Home change),
 * app/calendar/page.tsx's `load()`, and
 * app/settings/routines-reminders/page.tsx's `loadRoutines()`/`loadReminders()`
 * — see docs/mobile/ios-widgets.md for the full refresh-trigger list. Calls
 * are coalesced (`inFlight`) so back-to-back triggers (e.g. a mutation
 * followed immediately by its own reload) don't race two writes.
 */
export function syncWidgetSnapshot(): Promise<void> {
  if (!isNativeShell()) return Promise.resolve();
  // Best-effort background refresh: a broken/mocked api-client, a network
  // failure, or a native-plugin error must never surface as an unhandled
  // rejection to a caller that fires this with `void` (every call site
  // does — widget freshness is never allowed to block a user-facing flow
  // like login or saving an event).
  const run = (async () => {
    try {
      const homes = await api.homes();
      const activeHomeId = readStoredActiveHomeId();
      const activeHome = homes.find((h) => h.id === activeHomeId) ?? homes[0] ?? null;
      if (!activeHome) {
        await writeSnapshot(emptyHomeWidgetSnapshot());
        return;
      }

      const now = new Date();
      const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const monthEnd = new Date(now.getFullYear(), now.getMonth() + 2, 0);

      const [eventsResponse, routinesResponse, remindersResponse] = await Promise.all([
        api
          .listEvents(activeHome.id, {
            start_at: monthStart.toISOString(),
            end_at: monthEnd.toISOString(),
            page_size: 300,
          })
          .catch(() => ({ items: [] })),
        api.routines(activeHome.id).catch(() => ({ items: [] })),
        api.reminders(activeHome.id).catch(() => ({ items: [] })),
      ]);

      const snapshot = buildWidgetSnapshot({
        activeHome,
        occurrences: eventsResponse.items,
        routines: routinesResponse.items,
        reminders: remindersResponse.items,
        now,
      });
      await writeSnapshot(snapshot);
    } catch {
      // Swallow — see comment above. Nothing user-visible depends on this
      // succeeding; the next trigger (app resume, next mutation) retries.
    }
  })();
  inFlight = inFlight ? inFlight.then(() => run) : run;
  return inFlight;
}

/** Explicit logout path — must win over any in-flight sync so a slow
 * pre-logout fetch can never overwrite the cleared state afterwards. */
export async function clearWidgetSnapshot(): Promise<void> {
  if (!isNativeShell()) return;
  inFlight = (inFlight ?? Promise.resolve()).catch(() => undefined).then(async () => {
    await WidgetBridge.clearSnapshot();
  });
  await inFlight;
}

// Mirrors use-active-home.ts's own storage key exactly — deliberately not
// imported from there (that module is a React context/hook; this is a
// plain function callable from native-auth.ts before any component has
// mounted). Both must keep reading/writing "mykhaya.activeHomeId".
function readStoredActiveHomeId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("mykhaya.activeHomeId");
}

/** Exposed for tests only; production callers should use signedOutWidgetSnapshot(). */
export const __private = { signedOutWidgetSnapshot };
