// The minimum documented contract between the shared web frontend and a
// future native shell (task §12) — deliberately not a generic event bus.
// Each variant below is a capability the task explicitly named as *future*
// work (native tab bar, unread badge, native auth UI, biometric unlock,
// external URL handling, native share sheet); none of them is implemented
// by this phase. This file exists so those future implementations agree on
// one shape up front, rather than each inventing its own ad hoc message.
//
// dispatchNativeBridgeEvent is a no-op today — outside the native shell
// there is nothing listening, and inside it there is no native-side
// listener yet either (that arrives with the real iOS project in Phase 4+).
// Call sites that already know their event (e.g. a future auth-state
// change) can start calling this now without waiting for the native side
// to exist.
export type NativeBridgeEvent =
  | { type: "navigation-changed"; path: string }
  | { type: "unread-count-changed"; count: number }
  | { type: "auth-state-changed"; signedIn: boolean }
  | { type: "request-biometric-unlock" }
  | { type: "open-external-url"; url: string }
  | { type: "share"; title: string; url: string };

export function dispatchNativeBridgeEvent(event: NativeBridgeEvent): void {
  void event;
}
