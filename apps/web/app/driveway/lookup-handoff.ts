import type { VehicleLookupResult } from "@mykhaya/shared-types";

const KEY = "mykhaya.driveway.lookup.handoff";

export function storeLookupHandoff(result: VehicleLookupResult): void {
  if (typeof window !== "undefined") window.sessionStorage.setItem(KEY, JSON.stringify({ result, storedAt: Date.now() }));
}

export function consumeLookupHandoff(): VehicleLookupResult | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(KEY);
  window.sessionStorage.removeItem(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { result?: VehicleLookupResult; storedAt?: number };
    return parsed.result && typeof parsed.storedAt === "number" && Date.now() - parsed.storedAt <= 600000 ? parsed.result : null;
  } catch {
    return null;
  }
}
