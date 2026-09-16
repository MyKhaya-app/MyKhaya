"use client";

import { useEffect } from "react";
import type {
  ProductUsageEventName,
  ProductUsageModule,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { nativePlatform } from "./native-runtime";

const SESSION_KEY = "mykhaya.product-usage.session";
const LAST_ACTIVITY_KEY = "mykhaya.product-usage.session-last-activity";
const SESSION_TIMEOUT_MS = 30 * 60 * 1000;

function usageSessionId(): string {
  const now = Date.now();
  const previous = Number(sessionStorage.getItem(LAST_ACTIVITY_KEY) ?? 0);
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id || !previous || now - previous > SESSION_TIMEOUT_MS) {
    id = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  sessionStorage.setItem(LAST_ACTIVITY_KEY, String(now));
  return id;
}

export function trackProductUsage(
  eventName: ProductUsageEventName,
  options: { module?: ProductUsageModule; homeId?: string; eventKey?: string } = {},
): void {
  if (typeof window === "undefined") return;
  const sessionId = usageSessionId();
  void api.productUsageEvent({
    event_name: eventName,
    platform: nativePlatform(),
    module: options.module,
    home_id: options.homeId,
    usage_session_id: sessionId,
    event_key: options.eventKey ?? `${eventName}:${sessionId}`,
  }).catch(() => undefined);
}

function moduleForPath(path: string): ProductUsageModule | undefined {
  if (path === "/home" || path === "/") return "home";
  if (path.startsWith("/calendar")) return "calendar";
  if (path.startsWith("/nudges")) return "nudges";
  if (path.startsWith("/lists")) return "lists";
  if (path.startsWith("/meal-plans")) return "meals";
  if (path.startsWith("/family")) return "family";
  if (path.startsWith("/notifications")) return "notifications";
  if (path.startsWith("/settings")) return "settings";
  return undefined;
}

export function useProductAnalytics(enabled: boolean, path: string, homeId?: string): void {
  useEffect(() => {
    if (!enabled) {
      // Do not carry an authenticated user's analytics session across logout
      // and a later login in the same browser/native web view.
      sessionStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(LAST_ACTIVITY_KEY);
      sessionStorage.removeItem("mykhaya.product-usage.app-open");
      return;
    }
    if (!sessionStorage.getItem("mykhaya.product-usage.app-open")) {
      sessionStorage.setItem("mykhaya.product-usage.app-open", "1");
      trackProductUsage("app_open", { eventKey: `app_open:${usageSessionId()}` });
    }
    const module = moduleForPath(path);
    if (!module) return;
    const eventName = module === "calendar" ? "calendar_viewed"
      : module === "nudges" ? "nudges_viewed"
      : module === "lists" ? "lists_viewed"
      : module === "meals" ? "meal_plan_viewed"
      : module === "family" ? "family_viewed"
      : module === "home" ? "home_viewed"
      : undefined;
    if (eventName) trackProductUsage(eventName, {
      module,
      homeId,
      eventKey: `view:${module}:${usageSessionId()}`,
    });
  }, [enabled, homeId, path]);
}
