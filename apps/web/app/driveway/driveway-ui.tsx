"use client";

// Small presentation pieces shared by the Driveway screens. Styles live in
// styles.css under the scoped .drv-* selectors.
import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { VehicleMot } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { contrastText } from "@mykhaya/design-tokens";
import { memberColour } from "@/components/avatar";
import { formatPlate, initials, type MotTone } from "./vehicle-display";

/** UK number plate chip. */
export function PlateChip({ registration, size = "sm" }: { registration: string | null | undefined; size?: "sm" | "md" }) {
  const plate = formatPlate(registration);
  if (!plate) return null;
  return <span className={`drv-plate drv-plate-${size}`}>{plate}</span>;
}

/** MOT status pill. Words always carry the meaning; colour only reinforces it. */
export function MotPill({ tone, children, variant = "default" }: { tone: MotTone; children: string; variant?: "default" | "list" | "onGreen" }) {
  return <span className={`drv-pill drv-pill-${tone} drv-pill-${variant}`}>{children}</span>;
}

/** Owner initials in the member's own colour (never colour alone: initials
 *  plus an accessible name). */
export function OwnerAvatar({ userId, name, colour }: { userId: string; name: string; colour: string | null | undefined }) {
  // Same colour source and inline-style approach as components/avatar.tsx.
  const background = memberColour(userId, colour);
  return (
    <span className="drv-owner-avatar" role="img" aria-label={`Owner: ${name}`} title={name} style={{ background, color: contrastText(background) }}>
      {initials(name)}
    </span>
  );
}

/** The automatic freshness check plus a manual refresh for one vehicle's
 *  MOT. Reading never contacts the provider: an `if_stale` request lets the
 *  server decide; only the Refresh button forces a check. */
export function useMotRefresh(homeId: string | null, vehicleId: string, mot: VehicleMot | null, onChange: (next: VehicleMot) => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const autoChecked = useRef(false);
  const canRefresh = Boolean(mot?.eligible && mot.provider_available && mot.has_registration);
  const stale = mot?.summary.stale ?? false;

  useEffect(() => {
    if (!homeId || autoChecked.current || !canRefresh || !stale) return;
    autoChecked.current = true;
    api
      .refreshVehicleMot(homeId, vehicleId, "if_stale")
      .then(onChange)
      .catch(() => {
        // A background freshness check never interrupts the page.
      });
  }, [homeId, vehicleId, canRefresh, stale, onChange]);

  async function refresh() {
    if (!homeId || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const next = await api.refreshVehicleMot(homeId, vehicleId, "force");
      onChange(next);
      if (next.refresh?.message) setMessage(next.refresh.message);
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.message : "We couldn't check the MOT right now.");
    } finally {
      setBusy(false);
    }
  }

  return { canRefresh, busy, message, refresh };
}

export function RefreshButton({ busy, onClick, onGreen = false }: { busy: boolean; onClick: () => void; onGreen?: boolean }) {
  return (
    <button
      type="button"
      className={`drv-icon-button${onGreen ? " drv-icon-button-on-green" : ""}`}
      aria-label={busy ? "Checking MOT status" : "Refresh MOT status"}
      aria-busy={busy}
      disabled={busy}
      onClick={onClick}
    >
      <RefreshCw size={18} aria-hidden="true" className={busy ? "drv-spin" : undefined} />
    </button>
  );
}
