"use client";

import { useEffect, useState } from "react";
import { App } from "@capacitor/app";
import { isNativeShell } from "@/components/native-runtime";

export function HomeHeroDate() {
  // Avoid rendering the server's date/timezone during hydration. The space
  // preserves the existing subtitle line until the device date is available.
  const [label, setLabel] = useState("\u00a0");

  useEffect(() => {
    let disposed = false;
    let timer: number;
    function refresh() {
      if (disposed) return;
      window.clearTimeout(timer);
      const now = new Date();
      const parts = new Intl.DateTimeFormat("en-GB", {
        weekday: "long", day: "numeric", month: "long",
      }).formatToParts(now);
      const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value;
      // Explicit punctuation keeps the requested format identical across ICU versions.
      setLabel(`${part("weekday")}, ${part("day")} ${part("month")}`);
      const midnight = new Date(now);
      midnight.setHours(24, 0, 0, 0);
      // Local midnight respects DST. A bounded recheck also catches device
      // clock/timezone changes while Home stays open, without rerendering it.
      timer = window.setTimeout(refresh, Math.min(midnight.getTime() - now.getTime(), 60_000));
    }
    function onVisibility() {
      if (document.visibilityState === "visible") refresh();
    }
    refresh();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", refresh);
    const nativeListener = isNativeShell()
      ? App.addListener("appStateChange", ({ isActive }) => { if (isActive) refresh(); })
      : undefined;
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", refresh);
      void nativeListener?.then((handle) => handle.remove()).catch(() => undefined);
    };
  }, []);

  return label;
}
