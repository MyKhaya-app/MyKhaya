import { registerPlugin } from "@capacitor/core";
import { api } from "@mykhaya/api-client";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { nativePlatform } from "./native-runtime";
import {
  type WidgetSnapshot,
  type WidgetCalendarRange,
  buildWidgetSnapshot,
  emptyHomeWidgetSnapshot,
  fallbackWidgetCalendarRange,
  signedOutWidgetSnapshot,
} from "./widget-snapshot";

/**
 * TS-side contract for the native `WidgetBridgePlugin` (Swift source in
 * apps/ios-shell/native/plugin/WidgetBridgePlugin.swift, installed into the
 * generated ios/ project by scripts/install-widget-sources.sh — see
 * docs/mobile/ios-widgets.md). This is a repo-local plugin with no Android
 * counterpart (Home Screen widgets are iOS WidgetKit-specific and
 * explicitly out of scope for Android per that doc) and not an npm
 * package: outside a real iOS native shell (an ordinary browser tab,
 * Vitest, Android, or an iOS build where the plugin hasn't been installed
 * yet) Capacitor's web fallback throws "not implemented" for every method,
 * which is why every export below is guarded by `nativePlatform() === "ios"`
 * rather than the more general `isNativeShell()` — confirmed necessary by a
 * real Android logout hang: `clearWidgetSnapshot()` throwing inside
 * `nativeLogout()`'s `finally` block aborted the caller's subsequent
 * `router.push("/login")`, leaving the UI on the authenticated page even
 * though the native session had already been cleared (Android Phase 2B).
 */
export interface WidgetBridgePlugin {
  /** Same Calendar.current/grid helper as the native Calendar widget. */
  getCalendarRange(): Promise<WidgetCalendarRange>;
  /** Atomically replaces the shared App Group snapshot with `json` (the
   *  JSON-encoded WidgetSnapshot) and requests WidgetKit reload every
   *  MyKhaya widget timeline. */
  setSnapshot(options: { json: string }): Promise<void>;
  /** Replaces the snapshot with the signed-out state and reloads timelines
   *  — called on logout so no household data lingers on the Home Screen. */
  clearSnapshot(): Promise<void>;
}

const WidgetBridge = registerPlugin<WidgetBridgePlugin>("WidgetBridge");

async function fetchWidgetEvents(homeId: string, range: { start_at: string; end_at: string }): Promise<EventOccurrence[]> {
  const ownEvents = async () => {
    const items: EventOccurrence[] = [];
    let page = 1;
    while (true) {
      const response = await api.listEvents(homeId, { ...range, page, page_size: 300 });
      items.push(...response.items);
      if (!response.next_page) return items;
      if (response.next_page <= page || response.next_page > 10_000) throw new Error("Invalid calendar pagination");
      page = response.next_page;
    }
  };
  const [own, shares] = await Promise.all([
    ownEvents().catch(() => []),
    api.sharedCalendars().catch(() => ({ items: [] })),
  ]);
  // Reuse the same accepted-share endpoints as the main Calendar. These
  // enforce recipient/category permissions and expand recurrences server-side.
  const shared = await Promise.all(shares.items.map((share) =>
    api.listSharedEvents(share.id, range).then((response) => response.items).catch(() => []),
  ));
  return [...new Map([...own, ...shared.flat()].map((event) => [event.occurrence_id, event])).values()];
}

let inFlight: Promise<void> | null = null;

async function writeSnapshot(snapshot: WidgetSnapshot): Promise<void> {
  if (nativePlatform() !== "ios") return;
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
  if (nativePlatform() !== "ios") return Promise.resolve();
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
      // Old App Store binaries don't yet implement this additive method.
      const calendarRange = await WidgetBridge.getCalendarRange().catch(() => fallbackWidgetCalendarRange(now));
      // The API accepts instants for both event kinds. Query the union of
      // timed local-midnight boundaries and canonical UTC all-day boundaries;
      // snapshot shaping then applies each kind's exact overlap semantics.
      // No fixed offset or all-day date conversion is involved.
      const queryStart = new Date(Math.min(Date.parse(calendarRange.startAt), Date.parse(`${calendarRange.startDate}T00:00:00Z`)));
      const queryEnd = new Date(Math.max(Date.parse(calendarRange.endAt), Date.parse(`${calendarRange.endDate}T00:00:00Z`),
        // Retain the existing Next Event widget's look-ahead horizon. Only
        // its next three results, not this whole horizon, enter the cache.
        new Date(now.getFullYear(), now.getMonth() + 2, 0).getTime()));

      const [occurrences, routinesResponse, remindersResponse] = await Promise.all([
        fetchWidgetEvents(activeHome.id, { start_at: queryStart.toISOString(), end_at: queryEnd.toISOString() }),
        api.routines(activeHome.id).catch(() => ({ items: [] })),
        api.reminders(activeHome.id).catch(() => ({ items: [] })),
      ]);

      const snapshot = buildWidgetSnapshot({
        activeHome,
        occurrences,
        calendarRange,
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
  if (nativePlatform() !== "ios") return;
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
