"use client";

import { useEffect, useState } from "react";

const DISMISSED_KEY = "mykhaya.install-prompt.dismissed-at";
const DISMISS_DAYS = 14;

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function isStandalone() {
  if (typeof window === "undefined") return true;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // iOS Safari's legacy standalone flag — not covered by display-mode media query.
    (window.navigator as unknown as { standalone?: boolean }).standalone ===
      true
  );
}

function isIos() {
  if (typeof navigator === "undefined") return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function wasRecentlyDismissed() {
  const raw =
    typeof window !== "undefined"
      ? window.localStorage.getItem(DISMISSED_KEY)
      : null;
  if (!raw) return false;
  const elapsedDays = (Date.now() - Number(raw)) / (1000 * 60 * 60 * 24);
  return elapsedDays < DISMISS_DAYS;
}

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [showIosGuidance, setShowIosGuidance] = useState(false);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    if (isStandalone() || wasRecentlyDismissed()) return;
    setDismissed(false);

    if (isIos()) {
      setShowIosGuidance(true);
      return;
    }

    function onBeforeInstallPrompt(event: Event) {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    return () =>
      window.removeEventListener(
        "beforeinstallprompt",
        onBeforeInstallPrompt,
      );
  }, []);

  function dismiss() {
    window.localStorage.setItem(DISMISSED_KEY, String(Date.now()));
    setDismissed(true);
    setDeferredPrompt(null);
    setShowIosGuidance(false);
  }

  async function install() {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    dismiss();
  }

  if (dismissed || (!deferredPrompt && !showIosGuidance)) return null;

  return (
    <div className="install-banner" role="complementary">
      {showIosGuidance ? (
        <p>
          Install MyKhaya: tap <strong>Share</strong>, then{" "}
          <strong>Add to Home Screen</strong>.
        </p>
      ) : (
        <p>Install MyKhaya on this device for quick, offline-ready access.</p>
      )}
      <div className="install-banner-actions">
        {!showIosGuidance && (
          <button type="button" onClick={install}>
            Install
          </button>
        )}
        <button type="button" className="secondary" onClick={dismiss}>
          Not now
        </button>
      </div>
    </div>
  );
}
