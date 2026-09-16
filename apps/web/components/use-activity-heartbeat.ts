"use client";

import { useEffect, useRef } from "react";
import { App } from "@capacitor/app";
import { api } from "@mykhaya/api-client";
import { isNativeShell } from "./native-runtime";

const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000;

export function useActivityHeartbeat(enabled: boolean): void {
  const sending = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    const native = isNativeShell();
    let active = native || document.visibilityState === "visible";
    let timer: number | undefined;
    let removeNative: (() => void) | undefined;
    const send = () => {
      if (!active || sending.current) return;
      sending.current = true;
      void api.activityHeartbeat().catch(() => undefined).finally(() => { sending.current = false; });
    };
    const start = () => {
      if (timer === undefined) timer = window.setInterval(send, HEARTBEAT_INTERVAL_MS);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const setActive = (next: boolean) => {
      active = next;
      if (active) { send(); start(); } else stop();
    };
    const onVisibility = () => setActive(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVisibility);
    if (native) {
      void App.addListener("appStateChange", ({ isActive }) => setActive(isActive)).then(
        (handle) => { removeNative = () => { void handle.remove(); }; },
      );
    }
    if (active) { send(); start(); }
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
      removeNative?.();
    };
  }, [enabled]);
}
