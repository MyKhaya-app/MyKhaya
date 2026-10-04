"use client";

import { useState } from "react";
import { BottomSheet } from "./bottom-sheet";
import { isNativeShell } from "./native-runtime";
import { useNotificationPermission } from "./use-notification-permission";
import { recordDismissal, wasRecentlyDismissed } from "./notification-permission-state";

/**
 * One-shot MyKhaya-branded notification recommendation, shown before the
 * native OS permission dialog ever appears, plus a re-orientation sheet if
 * the user has already denied permission at the OS level. Entirely
 * platform-agnostic: it reads NotificationPermissionStatus and calls the
 * hook's requestPermission()/openSettings() — no `if (iOS)`/`if (Android)`
 * branching lives here, only the one `isNativeShell()` visibility gate that
 * keeps this off ordinary browser/PWA sessions (which keep their own
 * separate web-push banner/flow, untouched by this component).
 */
export function NotificationPermissionPrompt() {
  const { status, loading, requestPermission, openSettings } = useNotificationPermission();
  const [dismissedThisSession, setDismissedThisSession] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!isNativeShell() || loading || dismissedThisSession || wasRecentlyDismissed()) return null;

  const variant = status === "not_requested" ? "recommend" : status === "denied" ? "denied" : null;
  if (!variant) return null;

  function dismiss() {
    recordDismissal();
    setDismissedThisSession(true);
  }

  async function primaryAction() {
    setBusy(true);
    try {
      if (variant === "recommend") {
        await requestPermission();
      } else {
        await openSettings();
      }
    } finally {
      setBusy(false);
      // Not a "dismissal" in the Not-now sense — no cooldown recorded, the
      // sheet simply won't show again because status itself has moved on
      // (granted/denied) or the user is now away in system Settings.
      setDismissedThisSession(true);
    }
  }

  const copy =
    variant === "recommend"
      ? {
          title: "Stay in the loop",
          body: (
            <>
              <p>MyKhaya works best when notifications are enabled.</p>
              <p>
                We&rsquo;ll let you know about things like family events, reminders, Nudges and
                important Home activity.
              </p>
              <p>
                You stay in control. Choose exactly which notifications you want at any time in
                MyKhaya Settings.
              </p>
            </>
          ),
          primaryLabel: "Enable notifications",
          secondaryLabel: "Not now",
        }
      : {
          title: "Notifications are turned off",
          body: (
            <>
              <p>MyKhaya can&rsquo;t currently send notifications to this device.</p>
              <p>You can enable them from your phone&rsquo;s settings.</p>
            </>
          ),
          primaryLabel: "Open phone settings",
          secondaryLabel: "Maybe later",
        };

  return (
    <BottomSheet
      title={copy.title}
      onDismiss={dismiss}
      footer={
        <div className="notification-permission-actions">
          <button type="button" disabled={busy} onClick={() => void primaryAction()}>
            {copy.primaryLabel}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={dismiss}>
            {copy.secondaryLabel}
          </button>
        </div>
      }
    >
      {copy.body}
    </BottomSheet>
  );
}
